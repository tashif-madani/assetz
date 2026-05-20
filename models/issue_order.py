from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AssetIssueOrder(models.Model):
    """Asset Issue Order - flexible recipient assignment workflow."""

    _name = "assetz.issue.order"
    _description = "Asset Issue Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # FLEXIBLE RECIPIENT - Issue to ANY of these
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
        string="Recipient",
        compute="_compute_recipient_display",
        store=True,
    )

    # Issue details
    issue_type = fields.Selection(
        selection=[
            ("permanent", "Permanent Assignment"),
            ("temporary", "Temporary/Loan"),
            ("transfer", "Transfer to Location"),
            ("project", "Project Assignment"),
            ("rental", "Rental/Lease"),
            ("demo", "Demo/Trial"),
        ],
        string="Issue Type",
        default="permanent",
        required=True,
        tracking=True,
    )

    issue_date = fields.Date(
        string="Issue Date",
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    expected_return_date = fields.Date(
        string="Expected Return Date",
        tracking=True,
    )
    actual_return_date = fields.Date(
        string="Actual Return Date",
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("issued", "Issued"),
            ("partial_return", "Partially Returned"),
            ("returned", "Fully Returned"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    line_ids = fields.One2many(
        comodel_name="assetz.issue.order.line",
        inverse_name="order_id",
        string="Assets",
    )

    # Approval workflow
    require_approval = fields.Boolean(
        string="Requires Approval",
        help="If checked, this order requires approval before issuing",
    )
    approved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
        tracking=True,
    )
    approved_date = fields.Datetime(
        string="Approval Date",
        tracking=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
    )

    # Signature collection
    require_signature = fields.Boolean(
        string="Require Digital Signature",
    )
    signature = fields.Binary(
        string="Recipient Signature",
    )
    signed_by = fields.Char(
        string="Signed By",
    )
    signed_date = fields.Datetime(
        string="Signature Date",
    )

    # Source and destination
    source_location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Issued From",
        required=True,
        tracking=True,
        help="Select the location from which assets will be issued. Only assets at this location will be available for selection.",
    )

    # Additional info
    notes = fields.Text(
        string="Notes/Terms & Conditions",
    )
    reason = fields.Text(
        string="Issue Reason",
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
    returned_count = fields.Integer(
        string="Returned Count",
        compute="_compute_asset_count",
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
        for order in self:
            if order.recipient_type == "employee" and order.employee_id:
                order.recipient_display = order.employee_id.name
            elif order.recipient_type == "user" and order.user_id:
                order.recipient_display = order.user_id.name
            elif order.recipient_type == "partner" and order.partner_id:
                order.recipient_display = order.partner_id.name
            elif order.recipient_type == "department" and order.department_id:
                order.recipient_display = order.department_id.name
            elif order.recipient_type == "location" and order.location_id:
                order.recipient_display = order.location_id.complete_name
            elif order.recipient_type == "project" and order.project_name:
                order.recipient_display = order.project_name
            elif order.recipient_type == "cost_center" and order.cost_center:
                order.recipient_display = f"Cost Center: {order.cost_center}"
            elif order.recipient_type == "other" and order.recipient_name:
                order.recipient_display = order.recipient_name
            else:
                order.recipient_display = "Not Specified"

    @api.depends("line_ids", "line_ids.returned")
    def _compute_asset_count(self):
        """Compute asset and returned counts."""
        for order in self:
            order.asset_count = len(order.line_ids)
            order.returned_count = len(order.line_ids.filtered("returned"))

    @api.onchange("source_location_id")
    def _onchange_source_location_id(self):
        """Update domain for asset selection when source location changes."""
        # Clear existing lines when source location changes (optional)
        # to prevent selecting assets from wrong location
        if self.source_location_id and self.line_ids:
            # Check if any selected assets are not in the new source location
            invalid_assets = self.line_ids.filtered(
                lambda l: l.asset_id and l.asset_id.location_id != self.source_location_id
            )
            if invalid_assets:
                return {
                    "warning": {
                        "title": "Source Location Changed",
                        "message": "Some selected assets are not at the new source location. "
                                   "Please review and update the asset selection.",
                    }
                }

    @api.model_create_multi
    def create(self, vals_list):
        """Generate order reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.issue.order"
                ) or "New"
        return super().create(vals_list)

    def action_confirm(self):
        """Confirm the issue order."""
        for order in self:
            if not order.line_ids:
                raise UserError("Please add at least one asset to issue.")

            # Check if any asset's category requires an approved request
            assets_requiring_request = []
            for line in order.line_ids:
                asset = line.asset_id
                if asset.category_id and asset.category_id.require_request:
                    # Check if there's an approved/fulfilled request for this asset
                    approved_request = self.env["assetz.asset.request"].search([
                        ("state", "in", ["approved", "fulfilled"]),
                        "|",
                        ("asset_id", "=", asset.id),
                        "&",
                        ("category_id", "=", asset.category_id.id),
                        ("assigned_asset_id", "=", asset.id),
                    ], limit=1)
                    if not approved_request:
                        assets_requiring_request.append(asset.name)

            if assets_requiring_request:
                asset_list = "\n• ".join(assets_requiring_request)
                raise UserError(
                    f"The following assets require an approved Asset Request before issuing:\n\n"
                    f"• {asset_list}\n\n"
                    "Please create and get approval for an Asset Request first, "
                    "or remove these assets from the issue order."
                )

            if order.require_approval:
                order.state = "pending_approval"
            else:
                order.state = "confirmed"

    def action_approve(self):
        """Approve the issue order."""
        self.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Datetime.now(),
        })

    def action_reject(self):
        """Reject the issue order (opens wizard for reason)."""
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.issue.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def action_issue(self):
        """Issue the assets to the recipient."""
        for order in self:
            if order.require_signature and not order.signature:
                raise UserError("Recipient signature is required before issuing.")

            # Check if any assets are already issued or reserved
            unavailable_assets = order.line_ids.filtered(
                lambda l: l.asset_id.issue_state != "available"
            )
            if unavailable_assets:
                asset_details = []
                for line in unavailable_assets:
                    status = dict(line.asset_id._fields['issue_state'].selection).get(
                        line.asset_id.issue_state, line.asset_id.issue_state
                    )
                    asset_details.append(f"{line.asset_id.name} ({status})")
                raise UserError(
                    f"The following assets are not available and cannot be issued:\n" +
                    "\n".join(asset_details)
                )

            # Update asset states
            for line in order.line_ids:
                asset_vals = {
                    "issue_state": "issued",
                    "current_holder_type": order.recipient_type,
                    "current_holder_display": order.recipient_display,
                    "issue_date": order.issue_date,
                    "expected_return_date": order.expected_return_date,
                    "last_issue_order_id": order.id,
                }

                # Update assigned_to_id based on recipient type
                if order.recipient_type == "user" and order.user_id:
                    asset_vals["assigned_to_id"] = order.user_id.id
                elif order.recipient_type == "employee" and order.employee_id:
                    # Get the user linked to the employee if any
                    if order.employee_id.user_id:
                        asset_vals["assigned_to_id"] = order.employee_id.user_id.id

                # Update location_id based on recipient type
                if order.recipient_type == "location" and order.location_id:
                    asset_vals["location_id"] = order.location_id.id

                # Update department_id
                if order.recipient_type == "department" and order.department_id:
                    asset_vals["department_id"] = order.department_id.id

                line.asset_id.write(asset_vals)

                # Log movement if enabled
                if self.env["ir.config_parameter"].sudo().get_param(
                    "assetz.enable_movement_logging", "False"
                ) == "True":
                    self.env["assetz.asset.movement"].create({
                        "asset_id": line.asset_id.id,
                        "from_location_id": order.source_location_id.id if order.source_location_id else False,
                        "to_location_id": order.location_id.id if order.recipient_type == "location" else False,
                        "movement_type": "issue",
                        "reason": order.reason,
                        "reference_type": "issue_order",
                        "reference_id": order.id,
                    })

            order.state = "issued"

    def action_return(self):
        """Return all assets."""
        for order in self:
            for line in order.line_ids.filtered(lambda l: not l.returned):
                line.returned = True
                line.return_date = fields.Date.today()
                line.asset_id.write({
                    "issue_state": "available",
                    "current_holder_type": False,
                    "current_holder_display": False,
                    "issue_date": False,
                    "expected_return_date": False,
                    "assigned_to_id": False,
                    # Note: location_id and department_id are not cleared
                    # as they may represent where the asset is returned to
                })

            order.actual_return_date = fields.Date.today()
            order.state = "returned"

    def action_cancel(self):
        """Cancel the issue order."""
        for order in self:
            # If order was issued, revert asset states
            if order.state in ("issued", "partial_return"):
                for line in order.line_ids.filtered(lambda l: not l.returned):
                    line.asset_id.write({
                        "issue_state": "available",
                        "current_holder_type": False,
                        "current_holder_display": False,
                        "issue_date": False,
                        "expected_return_date": False,
                        "assigned_to_id": False,
                    })
            order.state = "cancelled"

    def action_draft(self):
        """Reset to draft state."""
        self.write({"state": "draft"})


class AssetIssueOrderLine(models.Model):
    """Issue Order Line - individual asset in an issue order."""

    _name = "assetz.issue.order.line"
    _description = "Asset Issue Order Line"
    _order = "sequence, id"

    order_id = fields.Many2one(
        comodel_name="assetz.issue.order",
        string="Issue Order",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)

    # Related field to get source location from order for domain filtering
    source_location_id = fields.Many2one(
        related="order_id.source_location_id",
        string="Source Location",
        store=False,
    )

    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
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

    quantity = fields.Float(
        string="Quantity",
        default=1.0,
        help="Quantity for consumable-type assets",
    )

    condition_on_issue = fields.Selection(
        selection=[
            ("new", "New"),
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("poor", "Poor"),
        ],
        string="Condition on Issue",
        default="good",
    )
    condition_on_return = fields.Selection(
        selection=[
            ("new", "New"),
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("poor", "Poor"),
            ("damaged", "Damaged"),
            ("lost", "Lost"),
        ],
        string="Condition on Return",
    )

    notes = fields.Text(string="Notes")

    # Return tracking
    returned = fields.Boolean(
        string="Returned",
        default=False,
    )
    return_date = fields.Date(
        string="Return Date",
    )

    @api.constrains("asset_id", "order_id")
    def _check_asset_availability(self):
        """Ensure asset is available for issuance."""
        for line in self:
            # Skip validation if order is already issued (editing existing lines)
            if line.order_id.state in ("issued", "partial_return", "returned"):
                continue
            if line.asset_id.issue_state != "available":
                raise ValidationError(
                    f"Asset '{line.asset_id.name}' is not available for issuance. "
                    f"Current status: {dict(line.asset_id._fields['issue_state'].selection).get(line.asset_id.issue_state, line.asset_id.issue_state)}"
                )

    def action_return_asset(self):
        """Return this specific asset."""
        for line in self:
            line.returned = True
            line.return_date = fields.Date.today()
            line.asset_id.write({
                "issue_state": "available",
                "current_holder_type": False,
                "current_holder_display": False,
                "issue_date": False,
                "expected_return_date": False,
                "assigned_to_id": False,
            })

            # Check if all assets returned
            if all(l.returned for l in line.order_id.line_ids):
                line.order_id.state = "returned"
                line.order_id.actual_return_date = fields.Date.today()
            else:
                line.order_id.state = "partial_return"


class AssetIssueRejectWizard(models.TransientModel):
    """Wizard for rejecting issue orders with reason."""

    _name = "assetz.issue.reject.wizard"
    _description = "Issue Order Rejection Wizard"

    order_id = fields.Many2one(
        comodel_name="assetz.issue.order",
        string="Issue Order",
        required=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        """Reject the order with the provided reason."""
        self.order_id.write({
            "state": "cancelled",
            "rejection_reason": self.reason,
        })
        return {"type": "ir.actions.act_window_close"}
