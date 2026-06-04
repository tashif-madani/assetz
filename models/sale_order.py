from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
    # Service / Rental picker. Options are filtered by the company toggles
    # in Settings → Orders so an admin can disable a whole order type.
    # Kept in sync with sale_renting's is_rental_order via onchange in both
    # directions so either field stays canonical.
    assetz_order_type = fields.Selection(
        selection="_selection_assetz_order_type",
        string="Order Type",
        default=lambda self: self._default_assetz_order_type(),
        tracking=True,
    )

    @api.model
    def _selection_assetz_order_type(self):
        """Return only the order types enabled in company settings."""
        company = self.env.company
        options = []
        if company.assetz_enable_service_types_service:
            options.append(("service", "Service Order"))
        if company.assetz_enable_service_types_rental:
            options.append(("rental", "Rental Order"))
        if not options:
            # Fallback so the form still works if an admin unchecked both.
            options = [
                ("service", "Service Order"),
                ("rental", "Rental Order"),
            ]
        return options

    @api.model
    def _default_assetz_order_type(self):
        """Pick the first enabled order type as the default for new orders."""
        company = self.env.company
        if company.assetz_enable_service_types_service:
            return "service"
        if company.assetz_enable_service_types_rental:
            return "rental"
        return "service"

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
        tracking=True,
        # No default + not required — service orders skip the recipient group
        # entirely; rental orders show it and the user can pick when relevant.
    )
    recipient_employee_id = fields.Many2one(
        "hr.employee", string="Recipient (Employee)", tracking=True)
    recipient_user_id = fields.Many2one(
        "res.users", string="Recipient (User)", tracking=True)
    recipient_partner_id = fields.Many2one(
        "res.partner", string="Recipient (Contact)", tracking=True)
    recipient_department_id = fields.Many2one(
        "hr.department", string="Recipient (Department)", tracking=True)
    recipient_location_id = fields.Many2one(
        "assetz.location", string="Recipient (Location)", tracking=True)
    recipient_project_name = fields.Char(
        string="Recipient (Project)", tracking=True)
    recipient_cost_center = fields.Char(
        string="Recipient (Cost Center)", tracking=True)
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

    # True when the order has at least one service-typed product line.
    # Drives the Confirm button (a Service Order can't be confirmed empty)
    # and the server-side guard in action_confirm.
    assetz_has_service_line = fields.Boolean(
        string="Has Service Line",
        compute="_compute_assetz_has_service_line",
    )

    # Equipments — owned by our dedicated assetz.order.equipment model so we
    # control add/remove/qty cleanly (vs. sale.order.option which fights the
    # sale_management quoting flow).
    assetz_equipment_line_ids = fields.One2many(
        "assetz.order.equipment",
        "order_id",
        string="Equipments",
        copy=True,
    )

    @api.depends("order_line", "order_line.product_id", "order_line.display_type")
    def _compute_assetz_has_service_line(self):
        for order in self:
            order.assetz_has_service_line = any(
                line.product_id and line.product_id.type == "service"
                for line in order.order_line
                if not line.display_type  # ignore section/note rows
            )

    @api.onchange("order_line")
    def _onchange_order_line_assetz_seed_equipment(self):
        """Keep the Equipments tab (assetz_equipment_line_ids) in sync with
        the current service lines:
          - add equipment when a service line is added,
          - remove auto-added equipment when its source service is gone.

        Drops all rows flagged `assetz_auto_added` and re-creates them from
        scratch each time order_line changes. Manual rows (flag False)
        are left untouched.

        Lives on sale.order (parent) — Odoo's UI reliably propagates
        a parent's own One2many changes; cross-One2many edits from a
        child's onchange don't always reflect immediately.
        """
        if not self.is_assetz_order:
            return

        # 1. Drop our previously auto-added rows. The `-` operator on a
        #    recordset produces a new one without those records, which the
        #    onchange round-trip correctly translates into unlink commands.
        auto_added = self.assetz_equipment_line_ids.filtered("assetz_auto_added")
        if auto_added:
            self.assetz_equipment_line_ids = self.assetz_equipment_line_ids - auto_added

        # 2. Track manual product ids so we don't shadow them.
        manual_product_ids = set(
            self.assetz_equipment_line_ids.mapped("equipment_id").ids
        )
        already_added_product_ids = set()

        # 3. Re-add equipment for every current service line. Shared
        #    equipment is added once; we remember its source service so
        #    qty edits can sync back to the master.
        for line in self.order_line:
            if not (line.product_id and line.product_id.type == "service"):
                continue
            for eq in line.product_id.product_tmpl_id.assetz_equipment_line_ids:
                if eq.equipment_id.id in manual_product_ids:
                    continue
                if eq.equipment_id.id in already_added_product_ids:
                    continue
                new_row = self.env["assetz.order.equipment"].new({
                    "equipment_id": eq.equipment_id.id,
                    "quantity": eq.quantity,
                    "note": eq.note or eq.equipment_id.display_name,
                    "assetz_auto_added": True,
                    "assetz_source_service_product_id": line.product_id.id,
                })
                self.assetz_equipment_line_ids += new_row
                already_added_product_ids.add(eq.equipment_id.id)

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
            order.recipient_display = mapping.get(
                order.recipient_type) or "Not Specified"

    def action_view_assetz_job(self):
        """Open the single FSM task tied to this Assetz order.

        Note: kept under a distinct name (not `action_view_task`) because
        sale_project already defines `action_view_task` for its own Tasks
        smart button — overriding that name would break non-Assetz orders.
        """
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
            type_label = {"service": "Service Order", "rental": "Rental Order"}.get(
                order.assetz_order_type, ""
            )
            job_number = self.env["ir.sequence"].next_by_code("assetz.job.number") or False
            task = Task.create({
                "name": f"{order.name} — {type_label}".strip(" —"),
                "project_id": project.id,
                "partner_id": order.partner_id.id,
                "sale_order_id": order.id,
                "asset_id": representative_asset.id if representative_asset else False,
                "description": "\n".join(descr_parts) or False,
                # Planned/end date left empty on purpose — the user picks it
                # in the Job's Schedule panel; we don't auto-fill it.
                "company_id": order.company_id.id,
                "assetz_job_number": job_number,
            })
            order.task_id = task.id

            # ----- Bookend: Arrive at Location (always first) ----------
            # Sequence 10 keeps it ahead of every service section
            # (services start at 100). user_ids cleared because all
            # Assetz tasks use assetz_technician_ids (hr.employee) for
            # crew assignment — leaving user_ids on Administrator would
            # trigger project_enterprise's "N tasks at the same time"
            # planning_overlap warning across the bookend + sub-tasks.
            Task.create({
                "name": "Arrive at Location",
                "project_id": project.id,
                "parent_id": task.id,
                "partner_id": order.partner_id.id,
                "sale_order_id": order.id,
                "company_id": order.company_id.id,
                "sequence": 10,
                "assetz_is_arrival": True,
                "user_ids": [(5,)],
            })

            # Per service line: one section header (display_type='line_section')
            # + 5 regular sub-tasks ("Task 1" … "Task 5"). All children of
            # the main FSM task, ordered by sequence. Sequence spacing of
            # 100 leaves room for users to insert new tasks under each
            # section via the +Add Task button without renumbering.
            # Mirrors IWS's `_create_iws_predefined_tasks` pattern.
            seq = 100
            for sline in service_lines:
                # Section header row — visual only, no work fields.
                Task.create({
                    "name": sline.product_id.name,
                    "project_id": project.id,
                    "parent_id": task.id,
                    "sale_order_id": order.id,
                    "company_id": order.company_id.id,
                    "display_type": "line_section",
                    "sequence": seq,
                    "user_ids": [(5,)],
                })
                # 5 default tasks under this service.
                for i in range(1, 6):
                    Task.create({
                        "name": f"Task {i}",
                        "project_id": project.id,
                        "parent_id": task.id,
                        "partner_id": order.partner_id.id,
                        "sale_order_id": order.id,
                        "company_id": order.company_id.id,
                        "sequence": seq + i,
                        "asset_id": (
                            sline.asset_id.id if sline.asset_id
                            else representative_asset.id if representative_asset
                            else False
                        ),
                        "user_ids": [(5,)],
                    })
                seq += 100

            # ----- Bookend: Leave Location (always last) ---------------
            Task.create({
                "name": "Leave Location",
                "project_id": project.id,
                "parent_id": task.id,
                "partner_id": order.partner_id.id,
                "sale_order_id": order.id,
                "company_id": order.company_id.id,
                "sequence": seq if service_lines else 9999,
                "assetz_is_departure": True,
                "user_ids": [(5,)],
            })

    def _create_deliveries_for_job(self):
        """Create outward + inward stock.pickings linked to the FSM task,
        carrying the equipment from assetz_equipment_line_ids. Idempotent:
        if deliveries already exist on the task, do nothing.

        Mirrors IWS's `_create_iws_delivery_transfers()` (one outward +
        one inward, linked back via stock.picking.assetz_job_id).
        """
        Picking = self.env["stock.picking"]
        Move = self.env["stock.move"]
        customer_loc = self.env.ref("stock.stock_location_customers", raise_if_not_found=False)
        if not customer_loc:
            return
        for order in self:
            if not (order.is_assetz_order and order.task_id):
                continue
            if order.task_id.assetz_delivery_ids:
                continue
            # No equipment to move → no deliveries needed. Creating empty
            # pickings and then calling action_assign() would raise
            # "Nothing to check the availability for." (stock_picking.py),
            # because the picking has zero stock moves.
            if not order.assetz_equipment_line_ids:
                continue
            warehouse = self.env["stock.warehouse"].search(
                [("company_id", "=", order.company_id.id)], limit=1,
            )
            if not warehouse:
                continue

            created_pickings = self.env["stock.picking"]
            for transfer_type, picking_type, src, dest in (
                ("outward", warehouse.out_type_id, warehouse.lot_stock_id, customer_loc),
                ("inward", warehouse.in_type_id, customer_loc, warehouse.lot_stock_id),
            ):
                picking = Picking.create({
                    "partner_id": order.partner_id.id,
                    "picking_type_id": picking_type.id,
                    "location_id": src.id,
                    "location_dest_id": dest.id,
                    "assetz_job_id": order.task_id.id,
                    "assetz_transfer_type": transfer_type,
                    "origin": order.name,
                    "company_id": order.company_id.id,
                })
                for eq in order.assetz_equipment_line_ids:
                    Move.create({
                        "name": eq.equipment_id.display_name,
                        "product_id": eq.equipment_id.id,
                        "product_uom_qty": eq.quantity,
                        "product_uom": eq.equipment_id.uom_id.id,
                        "picking_id": picking.id,
                        "location_id": picking.location_id.id,
                        "location_dest_id": picking.location_dest_id.id,
                        "company_id": order.company_id.id,
                    })
                created_pickings |= picking

            # Advance both pickings from Draft → Confirmed → Assigned (Ready).
            # action_assign attempts to reserve stock; if stock isn't available
            # the picking lands in Waiting / Partially Available, which is fine
            # for the UI ("Ready"-ish indicator).
            if created_pickings:
                created_pickings.action_confirm()
                # Only assign pickings that actually carry moves, so an
                # empty picking can never trigger the stock "Nothing to
                # check the availability for." error.
                created_pickings.filtered(lambda p: p.move_ids).action_assign()

    def action_confirm(self):
        """Standard sale.order confirm + spawn FSM task + create deliveries.

        A Service Order must carry at least one service line before it can
        be confirmed (the Confirm button is also hidden in the view until
        then; this guard also covers the keyboard hotkey).
        """
        for order in self:
            if (
                order.is_assetz_order
                and order.assetz_order_type == "service"
                and not order.assetz_has_service_line
            ):
                raise UserError(_(
                    "Add at least one service in the Services tab before "
                    "confirming a Service Order."
                ))
        result = super().action_confirm()
        self._create_fsm_task_for_order()
        self._create_deliveries_for_job()
        return result


class SaleOrderLine(models.Model):
    """Asset reference on a sale order line — used by rental lines (the asset
    being rented) and optionally by service lines (the asset the service
    applies to). Also seeds the order's Equipments tab with the equipment
    required by service products (see product_template.assetz_equipment_line_ids).
    """

    _inherit = "sale.order.line"

    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        help="For rental lines, the asset being rented. Optional for services.",
    )

