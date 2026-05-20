from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetRequest(models.Model):
    """Asset Request - employee/user request workflow with approval."""

    _name = "assetz.asset.request"
    _description = "Asset Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Request Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # Requester (configurable)
    requester_type = fields.Selection(
        selection=[
            ("employee", "Employee"),
            ("user", "System User"),
            ("partner", "External Contact"),
        ],
        string="Requester Type",
        default="user",
        required=True,
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Requesting Employee",
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Requesting User",
        default=lambda self: self.env.user,
        tracking=True,
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Requesting Contact",
        tracking=True,
    )

    # Computed requester display
    requester_display = fields.Char(
        string="Requester",
        compute="_compute_requester_display",
        store=True,
    )

    # What they're requesting
    request_type = fields.Selection(
        selection=[
            ("specific", "Specific Asset"),
            ("category", "Any from Category"),
            ("new", "New Asset Purchase"),
        ],
        string="Request Type",
        default="category",
        required=True,
        tracking=True,
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Specific Asset",
        tracking=True,
        domain="[('state', 'in', ('active', 'maintenance'))]",
        help="Select any asset - if unavailable, you can create a Purchase Request after approval",
    )
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Asset Category",
        tracking=True,
    )
    quantity = fields.Integer(
        string="Quantity",
        default=1,
    )

    # Request details
    reason = fields.Text(
        string="Business Justification",
        required=True,
    )
    needed_by_date = fields.Date(
        string="Required By",
        tracking=True,
    )
    duration_type = fields.Selection(
        selection=[
            ("permanent", "Permanent Assignment"),
            ("temporary", "Temporary (specify return date)"),
            ("project", "Project Duration"),
        ],
        string="Duration",
        default="permanent",
    )
    return_date = fields.Date(
        string="Expected Return Date",
    )
    project_name = fields.Char(
        string="Project Name",
        help="Project name if duration is 'Project Duration'",
    )

    # Priority
    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Normal"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        string="Priority",
        default="1",
    )

    # Workflow state
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("manager_approval", "Pending Manager Approval"),
            ("asset_team_approval", "Pending Asset Team Approval"),
            ("approved", "Approved"),
            ("purchase_pending", "Purchase Pending"),
            ("assets_ready", "Assets Ready"),
            ("rejected", "Rejected"),
            ("fulfilled", "Fulfilled"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    # Approval workflow
    manager_id = fields.Many2one(
        comodel_name="res.users",
        string="Approving Manager",
        tracking=True,
    )
    manager_approved = fields.Boolean(
        string="Manager Approved",
    )
    manager_approved_date = fields.Datetime(
        string="Manager Approval Date",
    )
    manager_notes = fields.Text(
        string="Manager Notes",
    )

    asset_team_approved = fields.Boolean(
        string="Asset Team Approved",
    )
    asset_team_approved_by = fields.Many2one(
        comodel_name="res.users",
        string="Asset Team Approver",
    )
    asset_team_approved_date = fields.Datetime(
        string="Asset Team Approval Date",
    )
    asset_team_notes = fields.Text(
        string="Asset Team Notes",
    )

    rejection_reason = fields.Text(
        string="Rejection Reason",
    )

    # Link to generated issue order
    issue_order_id = fields.Many2one(
        comodel_name="assetz.issue.order",
        string="Issue Order",
        readonly=True,
    )

    # Link to purchase request
    purchase_request_id = fields.Many2one(
        comodel_name="assetz.purchase.request",
        string="Purchase Request",
        readonly=True,
    )

    # Assets created from purchase (linked via purchase request)
    created_asset_ids = fields.One2many(
        comodel_name="assetz.asset",
        inverse_name="source_asset_request_id",
        string="Created Assets",
        help="Assets created from the purchase request linked to this asset request",
    )
    created_assets_count = fields.Integer(
        string="Created Assets Count",
        compute="_compute_created_assets_count",
    )

    # Assigned asset (after approval)
    assigned_asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Assigned Asset",
        tracking=True,
        domain="[('issue_state', '=', 'available'), ('state', '=', 'active')]",
    )

    # Computed field to check asset availability
    is_asset_available = fields.Boolean(
        string="Asset Available",
        compute="_compute_is_asset_available",
        help="Indicates whether the requested/assigned asset is currently available",
    )

    # Additional info
    notes = fields.Text(
        string="Additional Notes",
    )

    # Company
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    @api.depends("asset_id", "assigned_asset_id", "request_type", "category_id")
    def _compute_is_asset_available(self):
        """Check if the requested/assigned asset is available."""
        for request in self:
            if request.request_type == "specific" and request.asset_id:
                request.is_asset_available = (
                    request.asset_id.issue_state == "available" and
                    request.asset_id.state == "active"
                )
            elif request.assigned_asset_id:
                request.is_asset_available = (
                    request.assigned_asset_id.issue_state == "available" and
                    request.assigned_asset_id.state == "active"
                )
            elif request.request_type in ("category", "new") and request.category_id:
                # Check if any asset of this category is available
                available_asset = self.env["assetz.asset"].search([
                    ("category_id", "=", request.category_id.id),
                    ("issue_state", "=", "available"),
                    ("state", "=", "active"),
                ], limit=1)
                request.is_asset_available = bool(available_asset)
            else:
                request.is_asset_available = False

    @api.depends("created_asset_ids")
    def _compute_created_assets_count(self):
        """Compute count of created assets."""
        for request in self:
            request.created_assets_count = len(request.created_asset_ids)

    @api.depends("requester_type", "employee_id", "user_id", "partner_id")
    def _compute_requester_display(self):
        """Compute display name for requester."""
        for request in self:
            if request.requester_type == "employee" and request.employee_id:
                request.requester_display = request.employee_id.name
            elif request.requester_type == "user" and request.user_id:
                request.requester_display = request.user_id.name
            elif request.requester_type == "partner" and request.partner_id:
                request.requester_display = request.partner_id.name
            else:
                request.requester_display = "Not Specified"

    @api.model_create_multi
    def create(self, vals_list):
        """Generate request reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.asset.request"
                ) or "New"
        return super().create(vals_list)

    @api.onchange("requester_type")
    def _onchange_requester_type(self):
        """Set default requester based on type."""
        if self.requester_type == "user":
            self.user_id = self.env.user
            self.employee_id = False
            self.partner_id = False
        elif self.requester_type == "employee":
            # Try to find employee record for current user
            employee = self.env["hr.employee"].search(
                [("user_id", "=", self.env.user.id)], limit=1
            )
            self.employee_id = employee.id if employee else False
            self.user_id = False
            self.partner_id = False
        else:
            self.employee_id = False
            self.user_id = False

    @api.onchange("request_type")
    def _onchange_request_type(self):
        """Clear fields based on request type."""
        if self.request_type == "specific":
            self.category_id = False
        elif self.request_type == "category":
            self.asset_id = False

    @api.onchange("duration_type")
    def _onchange_duration_type(self):
        """Clear return date if permanent."""
        if self.duration_type == "permanent":
            self.return_date = False
            self.project_name = False
        elif self.duration_type != "project":
            self.project_name = False

    def action_submit(self):
        """Submit the request for approval."""
        for request in self:
            if not request.reason:
                raise UserError("Please provide a business justification.")
            if request.request_type == "specific" and not request.asset_id:
                raise UserError("Please select a specific asset.")
            if request.request_type == "category" and not request.category_id:
                raise UserError("Please select an asset category.")

            # NOTE: We no longer block submission for unavailable assets.
            # Requests can be raised for any asset. If unavailable at fulfillment,
            # the user can create a Purchase Request instead.

            # Check if manager approval is needed
            if request.manager_id:
                request.state = "manager_approval"
            else:
                request.state = "asset_team_approval"

    def action_manager_approve(self):
        """Manager approves the request."""
        self.write({
            "manager_approved": True,
            "manager_approved_date": fields.Datetime.now(),
            "state": "asset_team_approval",
        })

    def action_manager_reject(self):
        """Manager rejects the request."""
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id, "rejection_stage": "manager"},
        }

    def action_asset_team_approve(self):
        """Asset team approves the request."""
        self.write({
            "asset_team_approved": True,
            "asset_team_approved_by": self.env.user.id,
            "asset_team_approved_date": fields.Datetime.now(),
            "state": "approved",
        })

    def action_asset_team_reject(self):
        """Asset team rejects the request."""
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id, "rejection_stage": "asset_team"},
        }

    def action_fulfill(self):
        """Fulfill the request by creating an issue order."""
        for request in self:
            if request.state != "approved":
                raise UserError("Only approved requests can be fulfilled.")

            # Determine the asset to issue
            asset = request.asset_id or request.assigned_asset_id
            if not asset:
                raise UserError(
                    "Please assign an asset before fulfilling the request."
                )

            # Check if asset is still available
            if asset.issue_state != "available":
                status = dict(asset._fields['issue_state'].selection).get(
                    asset.issue_state, asset.issue_state
                )
                raise UserError(
                    f"Asset '{asset.name}' is no longer available. "
                    f"Current status: {status}. "
                    "Please assign a different asset."
                )

            # Determine recipient
            recipient_type = request.requester_type
            if recipient_type == "partner":
                recipient_type = "partner"

            # Create issue order
            issue_vals = {
                "recipient_type": recipient_type,
                "issue_type": (
                    "permanent" if request.duration_type == "permanent"
                    else "temporary" if request.duration_type == "temporary"
                    else "project"
                ),
                "issue_date": fields.Date.today(),
                "expected_return_date": request.return_date,
                "reason": request.reason,
                "notes": request.notes,
            }

            # Set recipient based on type
            if recipient_type == "employee":
                issue_vals["employee_id"] = request.employee_id.id
            elif recipient_type == "user":
                issue_vals["user_id"] = request.user_id.id
            elif recipient_type == "partner":
                issue_vals["partner_id"] = request.partner_id.id

            issue_order = self.env["assetz.issue.order"].create(issue_vals)

            # Add asset line
            self.env["assetz.issue.order.line"].create({
                "order_id": issue_order.id,
                "asset_id": asset.id,
            })

            request.write({
                "issue_order_id": issue_order.id,
                "state": "fulfilled",
            })

        return {
            "type": "ir.actions.act_window",
            "name": "Issue Order",
            "res_model": "assetz.issue.order",
            "view_mode": "form",
            "res_id": issue_order.id,
        }

    def action_create_purchase_request(self):
        """Create a purchase request when no asset is available."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError("Only approved requests can create purchase requests.")

        # Determine category - either from specific asset or direct selection
        category = self.category_id
        if self.request_type == "specific" and self.asset_id:
            category = self.asset_id.category_id

        if not category:
            raise UserError("Please specify a category for the purchase request.")

        # Get requester's department if available
        department = None
        if self.requester_type == "employee" and self.employee_id:
            department = self.employee_id.department_id

        # Create purchase request
        purchase_request_vals = {
            "asset_request_id": self.id,
            "category_id": category.id,
            "quantity": self.quantity or 1,
            "description": self.reason,
            "needed_by_date": self.needed_by_date,
            "reason": self.reason,
            "requested_by_id": self.user_id.id if self.user_id else self.env.user.id,
            "department_id": department.id if department else False,
        }

        purchase_request = self.env["assetz.purchase.request"].create(purchase_request_vals)

        self.write({
            "purchase_request_id": purchase_request.id,
            "state": "purchase_pending",
        })

        return {
            "type": "ir.actions.act_window",
            "name": "Purchase Request",
            "res_model": "assetz.purchase.request",
            "view_mode": "form",
            "res_id": purchase_request.id,
        }

    def action_view_purchase_request(self):
        """View the linked purchase request."""
        self.ensure_one()
        if not self.purchase_request_id:
            raise UserError("No purchase request linked to this request.")
        return {
            "type": "ir.actions.act_window",
            "name": "Purchase Request",
            "res_model": "assetz.purchase.request",
            "view_mode": "form",
            "res_id": self.purchase_request_id.id,
        }

    def action_issue_created_assets(self):
        """Issue the assets created from purchase to the requester."""
        self.ensure_one()
        if self.state != "assets_ready":
            raise UserError("Assets can only be issued when in 'Assets Ready' state.")

        if not self.created_asset_ids:
            raise UserError("No assets have been created yet for this request.")

        # Filter only available, active assets
        available_assets = self.created_asset_ids.filtered(
            lambda a: a.issue_state == "available" and a.state == "active"
        )
        if not available_assets:
            raise UserError(
                "No available assets to issue. Assets may need to be activated first."
            )

        # Determine recipient
        recipient_type = self.requester_type
        if recipient_type == "partner":
            recipient_type = "partner"

        # Create issue order
        issue_vals = {
            "recipient_type": recipient_type,
            "issue_type": (
                "permanent" if self.duration_type == "permanent"
                else "temporary" if self.duration_type == "temporary"
                else "project"
            ),
            "issue_date": fields.Date.today(),
            "expected_return_date": self.return_date,
            "reason": self.reason,
            "notes": self.notes,
        }

        # Set recipient based on type
        if recipient_type == "employee":
            issue_vals["employee_id"] = self.employee_id.id
        elif recipient_type == "user":
            issue_vals["user_id"] = self.user_id.id
        elif recipient_type == "partner":
            issue_vals["partner_id"] = self.partner_id.id

        issue_order = self.env["assetz.issue.order"].create(issue_vals)

        # Add asset lines for all available assets
        for asset in available_assets:
            self.env["assetz.issue.order.line"].create({
                "order_id": issue_order.id,
                "asset_id": asset.id,
            })

        self.write({
            "issue_order_id": issue_order.id,
            "state": "fulfilled",
        })

        return {
            "type": "ir.actions.act_window",
            "name": "Issue Order",
            "res_model": "assetz.issue.order",
            "view_mode": "form",
            "res_id": issue_order.id,
        }

    def action_view_created_assets(self):
        """View the assets created from purchase for this request."""
        self.ensure_one()
        if not self.created_asset_ids:
            raise UserError("No assets have been created yet for this request.")
        return {
            "type": "ir.actions.act_window",
            "name": "Created Assets",
            "res_model": "assetz.asset",
            "view_mode": "list,form",
            "domain": [("id", "in", self.created_asset_ids.ids)],
        }

    def action_cancel(self):
        """Cancel the request."""
        self.write({"state": "cancelled"})

    def action_draft(self):
        """Reset to draft state."""
        self.write({
            "state": "draft",
            "manager_approved": False,
            "manager_approved_date": False,
            "asset_team_approved": False,
            "asset_team_approved_by": False,
            "asset_team_approved_date": False,
            "rejection_reason": False,
        })


class AssetRequestRejectWizard(models.TransientModel):
    """Wizard for rejecting asset requests with reason."""

    _name = "assetz.request.reject.wizard"
    _description = "Asset Request Rejection Wizard"

    request_id = fields.Many2one(
        comodel_name="assetz.asset.request",
        string="Asset Request",
        required=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        """Reject the request with the provided reason."""
        self.request_id.write({
            "state": "rejected",
            "rejection_reason": self.reason,
        })
        return {"type": "ir.actions.act_window_close"}
