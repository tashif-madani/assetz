from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AssetReservation(models.Model):
    """Asset Reservation - reserve assets for future issuance."""

    _name = "assetz.reservation"
    _description = "Asset Reservation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "reservation_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # FLEXIBLE RECIPIENT - Reserve for ANY of these
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
        string="Reserve For",
        required=True,
        default="employee",
        tracking=True,
    )

    # Recipient references (show based on recipient_type)
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Employee",
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="System User",
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Contact",
        tracking=True,
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department",
        tracking=True,
    )
    location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Location",
        tracking=True,
    )
    project_name = fields.Char(
        string="Project Name",
        tracking=True,
    )
    cost_center = fields.Char(
        string="Cost Center",
        tracking=True,
    )
    recipient_name = fields.Char(
        string="Recipient Name",
        help="Free text recipient name for 'Other' type",
        tracking=True,
    )

    # Computed display name for recipient
    recipient_display = fields.Char(
        string="Reserved For",
        compute="_compute_recipient_display",
        store=True,
    )

    # Reservation details
    reservation_date = fields.Date(
        string="Reservation Date",
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    valid_from = fields.Date(
        string="Valid From",
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    valid_until = fields.Date(
        string="Valid Until",
        tracking=True,
        help="Leave empty for indefinite reservation",
    )
    reason = fields.Text(
        string="Reservation Reason",
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("expired", "Expired"),
            ("converted", "Converted to Issue"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    line_ids = fields.One2many(
        comodel_name="assetz.reservation.line",
        inverse_name="reservation_id",
        string="Assets",
    )

    # Link to issue order if converted
    issue_order_id = fields.Many2one(
        comodel_name="assetz.issue.order",
        string="Issue Order",
        readonly=True,
    )

    # Additional info
    notes = fields.Text(
        string="Notes",
    )

    # Company
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # Counts
    asset_count = fields.Integer(
        string="Asset Count",
        compute="_compute_asset_count",
    )

    # Reservation validity
    is_expired = fields.Boolean(
        string="Is Expired",
        compute="_compute_is_expired",
        store=True,
    )

    @api.depends(
        "recipient_type",
        "employee_id",
        "user_id",
        "partner_id",
        "department_id",
        "location_id",
        "project_name",
        "cost_center",
        "recipient_name",
    )
    def _compute_recipient_display(self):
        """Compute a display name for the recipient."""
        for reservation in self:
            if reservation.recipient_type == "employee" and reservation.employee_id:
                reservation.recipient_display = reservation.employee_id.name
            elif reservation.recipient_type == "user" and reservation.user_id:
                reservation.recipient_display = reservation.user_id.name
            elif reservation.recipient_type == "partner" and reservation.partner_id:
                reservation.recipient_display = reservation.partner_id.name
            elif reservation.recipient_type == "department" and reservation.department_id:
                reservation.recipient_display = reservation.department_id.name
            elif reservation.recipient_type == "location" and reservation.location_id:
                reservation.recipient_display = reservation.location_id.complete_name
            elif reservation.recipient_type == "project" and reservation.project_name:
                reservation.recipient_display = reservation.project_name
            elif reservation.recipient_type == "cost_center" and reservation.cost_center:
                reservation.recipient_display = f"Cost Center: {reservation.cost_center}"
            elif reservation.recipient_type == "other" and reservation.recipient_name:
                reservation.recipient_display = reservation.recipient_name
            else:
                reservation.recipient_display = "Not Specified"

    @api.depends("line_ids")
    def _compute_asset_count(self):
        """Compute asset count."""
        for reservation in self:
            reservation.asset_count = len(reservation.line_ids)

    @api.depends("valid_until", "state")
    def _compute_is_expired(self):
        """Check if reservation is expired."""
        today = fields.Date.today()
        for reservation in self:
            if reservation.state == "confirmed" and reservation.valid_until:
                reservation.is_expired = reservation.valid_until < today
            else:
                reservation.is_expired = False

    @api.model_create_multi
    def create(self, vals_list):
        """Generate reservation reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.reservation"
                ) or "New"
        return super().create(vals_list)

    def action_confirm(self):
        """Confirm the reservation and mark assets as reserved."""
        for reservation in self:
            if not reservation.line_ids:
                raise UserError("Please add at least one asset to reserve.")

            # Check if any assets are already reserved or issued
            unavailable = reservation.line_ids.filtered(
                lambda l: l.asset_id.issue_state != "available"
            )
            if unavailable:
                asset_names = ", ".join(unavailable.mapped("asset_id.name"))
                raise UserError(
                    f"The following assets are not available for reservation:\n{asset_names}"
                )

            # Update asset states
            for line in reservation.line_ids:
                line.asset_id.write({
                    "issue_state": "reserved",
                    "current_holder_type": reservation.recipient_type,
                    "current_holder_display": f"Reserved: {reservation.recipient_display}",
                })

            reservation.state = "confirmed"

    def action_cancel(self):
        """Cancel the reservation and release assets."""
        for reservation in self:
            if reservation.state == "confirmed":
                # Release assets
                for line in reservation.line_ids:
                    # Only release if still reserved (not already issued/converted)
                    if line.asset_id.issue_state == "reserved":
                        line.asset_id.write({
                            "issue_state": "available",
                            "current_holder_type": False,
                            "current_holder_display": False,
                        })
            reservation.state = "cancelled"

    def action_convert_to_issue(self):
        """Convert reservation to an issue order."""
        self.ensure_one()
        if self.state != "confirmed":
            raise UserError("Only confirmed reservations can be converted to issue orders.")

        # Create issue order
        issue_vals = {
            "recipient_type": self.recipient_type,
            "issue_type": "permanent",
            "issue_date": fields.Date.today(),
            "reason": self.reason,
            "notes": self.notes,
        }

        # Set recipient based on type
        if self.recipient_type == "employee":
            issue_vals["employee_id"] = self.employee_id.id
        elif self.recipient_type == "user":
            issue_vals["user_id"] = self.user_id.id
        elif self.recipient_type == "partner":
            issue_vals["partner_id"] = self.partner_id.id
        elif self.recipient_type == "department":
            issue_vals["department_id"] = self.department_id.id
        elif self.recipient_type == "location":
            issue_vals["location_id"] = self.location_id.id
        elif self.recipient_type == "project":
            issue_vals["project_name"] = self.project_name
        elif self.recipient_type == "cost_center":
            issue_vals["cost_center"] = self.cost_center
        elif self.recipient_type == "other":
            issue_vals["recipient_name"] = self.recipient_name

        issue_order = self.env["assetz.issue.order"].create(issue_vals)

        # Add asset lines - temporarily set assets to available for the constraint
        for line in self.line_ids:
            line.asset_id.write({"issue_state": "available"})
            self.env["assetz.issue.order.line"].create({
                "order_id": issue_order.id,
                "asset_id": line.asset_id.id,
                "condition_on_issue": "good",
            })

        self.write({
            "issue_order_id": issue_order.id,
            "state": "converted",
        })

        return {
            "type": "ir.actions.act_window",
            "name": "Issue Order",
            "res_model": "assetz.issue.order",
            "view_mode": "form",
            "res_id": issue_order.id,
        }

    def action_draft(self):
        """Reset to draft state."""
        for reservation in self:
            if reservation.state == "confirmed":
                # Release assets
                for line in reservation.line_ids:
                    if line.asset_id.issue_state == "reserved":
                        line.asset_id.write({
                            "issue_state": "available",
                            "current_holder_type": False,
                            "current_holder_display": False,
                        })
            reservation.state = "draft"

    @api.model
    def _cron_check_expired_reservations(self):
        """Cron job to check and expire reservations past valid_until date."""
        today = fields.Date.today()
        expired = self.search([
            ("state", "=", "confirmed"),
            ("valid_until", "<", today),
        ])
        for reservation in expired:
            # Release assets
            for line in reservation.line_ids:
                if line.asset_id.issue_state == "reserved":
                    line.asset_id.write({
                        "issue_state": "available",
                        "current_holder_type": False,
                        "current_holder_display": False,
                    })
            reservation.state = "expired"


class AssetReservationLine(models.Model):
    """Reservation Line - individual asset in a reservation."""

    _name = "assetz.reservation.line"
    _description = "Asset Reservation Line"
    _order = "sequence, id"

    reservation_id = fields.Many2one(
        comodel_name="assetz.reservation",
        string="Reservation",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)

    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
        domain="[('issue_state', '=', 'available'), ('state', '=', 'active')]",
    )
    asset_code = fields.Char(
        related="asset_id.code",
        string="Asset Code",
        store=True,
    )
    asset_category_id = fields.Many2one(
        related="asset_id.category_id",
        string="Category",
        store=True,
    )
    serial_number = fields.Char(
        related="asset_id.serial_number",
        string="Serial Number",
    )

    notes = fields.Text(string="Notes")

    @api.constrains("asset_id", "reservation_id")
    def _check_asset_availability(self):
        """Ensure asset is available for reservation."""
        for line in self:
            # Skip validation if reservation is already confirmed
            if line.reservation_id.state in ("confirmed", "converted", "expired"):
                continue
            if line.asset_id.issue_state != "available":
                raise ValidationError(
                    f"Asset '{line.asset_id.name}' is not available for reservation. "
                    f"Current status: {dict(line.asset_id._fields['issue_state'].selection).get(line.asset_id.issue_state, line.asset_id.issue_state)}"
                )
