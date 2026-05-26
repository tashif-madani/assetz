from odoo import api, fields, models


class SaleOrder(models.Model):
    """Extend sale.order with the Assetz-specific fields that used to live on
    the custom assetz.order: a flexible recipient (employee / department /
    location / project / etc.), an agreement link, and a flag that marks the
    order as managed by the Assetz app.

    Rental orders use the standard `is_rental_order` from `sale_renting`.
    Service orders are sale.orders with service-typed products on their lines.
    """

    _inherit = "sale.order"

    is_assetz_order = fields.Boolean(
        string="Assetz Order",
        default=False,
        copy=False,
        tracking=True,
        help="Marks this sale order as managed under Operations → Orders.",
    )

    # UI-friendly wrapper around is_rental_order: gives users a clear
    # Service / Rental picker. Kept in sync with sale_renting's is_rental_order
    # via onchange in both directions so either field stays canonical.
    assetz_order_type = fields.Selection(
        selection=[
            ("service", "Service Order"),
            ("rental", "Rental Order"),
        ],
        string="Order Type",
        default="service",
        tracking=True,
    )

    # Customer is sale.order.partner_id (standard). The recipient is who
    # actually receives the assets/services and may differ from the billable
    # customer (e.g. a department within the customer org).
    recipient_type = fields.Selection(
        selection=[
            ("employee", "Employee"),
            ("user", "System User"),
            ("partner", "Contact/Customer/Vendor"),
            ("department", "Department"),
            ("location", "Location/Site"),
            ("project", "Project"),
            ("cost_center", "Cost Center"),
            ("other", "Other (Free Text)"),
        ],
        string="Recipient Type",
        default="partner",
        tracking=True,
    )
    recipient_employee_id = fields.Many2one("hr.employee", string="Recipient (Employee)", tracking=True)
    recipient_user_id = fields.Many2one("res.users", string="Recipient (User)", tracking=True)
    recipient_partner_id = fields.Many2one("res.partner", string="Recipient (Contact)", tracking=True)
    recipient_department_id = fields.Many2one("hr.department", string="Recipient (Department)", tracking=True)
    recipient_location_id = fields.Many2one("assetz.location", string="Recipient (Location)", tracking=True)
    recipient_project_name = fields.Char(string="Recipient (Project)", tracking=True)
    recipient_cost_center = fields.Char(string="Recipient (Cost Center)", tracking=True)
    recipient_name = fields.Char(string="Recipient (Free Text)", tracking=True)
    recipient_display = fields.Char(
        string="Recipient",
        compute="_compute_recipient_display",
        store=True,
    )

    agreement_id = fields.Many2one(
        "assetz.agreement",
        string="Agreement",
        tracking=True,
        help="Pick a valid agreement for the selected customer.",
    )

    source_location_id = fields.Many2one(
        "assetz.location",
        string="Source Location",
        help="Where assets are picked from when issued.",
    )

    # Settings-driven feature flag (drives view visibility of the agreement field).
    show_agreements = fields.Boolean(
        compute="_compute_feature_flags",
        default=lambda self: self.env.company.assetz_enable_agreements,
    )

    # Link to the single FSM task (1:1) auto-created on confirm.
    task_id = fields.Many2one(
        "project.task",
        string="Job (FSM Task)",
        readonly=True,
        copy=False,
        help="FSM task spawned when the order is confirmed.",
    )

    @api.onchange("assetz_order_type")
    def _onchange_assetz_order_type(self):
        for order in self:
            order.is_rental_order = order.assetz_order_type == "rental"

    @api.onchange("is_rental_order")
    def _onchange_is_rental_order(self):
        for order in self:
            if order.is_assetz_order:
                order.assetz_order_type = "rental" if order.is_rental_order else "service"

    @api.depends("company_id", "company_id.assetz_enable_agreements")
    def _compute_feature_flags(self):
        env_company = self.env.company
        for order in self:
            company = order.company_id or env_company
            order.show_agreements = company.assetz_enable_agreements

    @api.depends(
        "recipient_type",
        "recipient_employee_id",
        "recipient_user_id",
        "recipient_partner_id",
        "recipient_department_id",
        "recipient_location_id",
        "recipient_project_name",
        "recipient_cost_center",
        "recipient_name",
    )
    def _compute_recipient_display(self):
        for order in self:
            mapping = {
                "employee": order.recipient_employee_id.name,
                "user": order.recipient_user_id.name,
                "partner": order.recipient_partner_id.name,
                "department": order.recipient_department_id.name,
                "location": (
                    order.recipient_location_id.complete_name
                    if order.recipient_location_id
                    else False
                ),
                "project": order.recipient_project_name,
                "cost_center": (
                    f"Cost Center: {order.recipient_cost_center}"
                    if order.recipient_cost_center
                    else False
                ),
                "other": order.recipient_name,
            }
            order.recipient_display = mapping.get(order.recipient_type) or "Not Specified"

    def action_view_task(self):
        """Open the single FSM task tied to this order."""
        self.ensure_one()
        if not self.task_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.task_id.name,
            "res_model": "project.task",
            "res_id": self.task_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def _get_or_create_fsm_project(self):
        """Find or create the shared FSM project used for all Assetz jobs.

        Kept generic — one project per company, named "Assetz Field Service".
        Multi-customer deployments can override via this method if they want
        per-customer or per-team projects.
        """
        Project = self.env["project.project"]
        project = Project.search(
            [("is_fsm", "=", True), ("name", "=", "Assetz Field Service")],
            limit=1,
        )
        if not project:
            project = Project.create({
                "name": "Assetz Field Service",
                "is_fsm": True,
                "company_id": self.env.company.id,
            })
        return project

    def _create_fsm_task_for_order(self):
        """Spawn exactly one project.task (is_fsm=True) per Assetz sale.order
        on confirm. Idempotent.
        """
        Task = self.env["project.task"]
        for order in self:
            if not order.is_assetz_order or order.task_id:
                continue

            asset_lines = order.order_line.filtered(lambda l: l.asset_id)
            service_lines = order.order_line.filtered(
                lambda l: l.product_id and l.product_id.type == "service"
            )
            representative_asset = asset_lines[:1].asset_id

            descr_parts = []
            if asset_lines:
                descr_parts.append(
                    "Assets: " + ", ".join(asset_lines.mapped("asset_id.name"))
                )
            if service_lines:
                descr_parts.append(
                    "Services: "
                    + ", ".join(
                        l.name or (l.product_id.name or "") for l in service_lines
                    )
                )
            if order.note:
                descr_parts.append(order.note)

            project = order._get_or_create_fsm_project()
            task = Task.create({
                "name": f"{order.name} — {dict(order._fields['assetz_order_type'].selection).get(order.assetz_order_type, '')}".strip(" —"),
                "project_id": project.id,
                "partner_id": order.partner_id.id,
                "sale_order_id": order.id,
                "asset_id": representative_asset.id if representative_asset else False,
                "description": "\n".join(descr_parts) or False,
                "date_deadline": (
                    (order.assetz_order_type == "rental" and order.rental_start_date)
                    or order.date_order
                ),
                "company_id": order.company_id.id,
            })
            order.task_id = task.id

    def action_confirm(self):
        """Standard sale.order confirm, plus spawn one FSM task for Assetz orders."""
        result = super().action_confirm()
        self._create_fsm_task_for_order()
        return result


class SaleOrderLine(models.Model):
    """Asset reference on a sale order line — used by rental lines (the asset
    being rented) and optionally by service lines (the asset the service
    applies to)."""

    _inherit = "sale.order.line"

    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        help="For rental lines, the asset being rented. Optional for services.",
    )
