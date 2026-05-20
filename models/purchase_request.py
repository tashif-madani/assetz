from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetPurchaseRequest(models.Model):
    """Asset Purchase Request - workflow for purchasing new assets."""

    _name = "assetz.purchase.request"
    _description = "Asset Purchase Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # Source - where this request came from
    asset_request_id = fields.Many2one(
        comodel_name="assetz.asset.request",
        string="Source Asset Request",
        readonly=True,
    )

    # What to purchase
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Asset Category",
        required=True,
        tracking=True,
    )
    quantity = fields.Integer(
        string="Quantity",
        default=1,
        required=True,
    )
    description = fields.Text(
        string="Specifications/Description",
        help="Detailed specifications for the assets to be purchased",
    )
    estimated_unit_cost = fields.Monetary(
        string="Estimated Unit Cost",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )
    total_estimated_cost = fields.Monetary(
        string="Total Estimated Cost",
        compute="_compute_total_cost",
        store=True,
        currency_field="currency_id",
    )

    # Vendor
    supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Preferred Supplier",
        domain="[('is_company', '=', True)]",
        tracking=True,
    )

    # Requester info
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        tracking=True,
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department",
    )
    needed_by_date = fields.Date(
        string="Required By",
        tracking=True,
    )
    reason = fields.Text(
        string="Business Justification",
    )

    # Approval workflow
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("po_created", "PO Created"),
            ("received", "Received"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    # Approval tracking
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

    # Link to Purchase Order
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Purchase Order",
        readonly=True,
    )

    # Link to created assets
    asset_ids = fields.One2many(
        comodel_name="assetz.asset",
        inverse_name="purchase_request_id",
        string="Created Assets",
    )
    assets_created_count = fields.Integer(
        string="Assets Created",
        compute="_compute_assets_created_count",
    )

    # Company
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # Notes
    notes = fields.Text(
        string="Notes",
    )

    @api.depends("estimated_unit_cost", "quantity")
    def _compute_total_cost(self):
        """Compute total estimated cost."""
        for request in self:
            request.total_estimated_cost = request.estimated_unit_cost * request.quantity

    @api.depends("asset_ids")
    def _compute_assets_created_count(self):
        """Compute count of created assets."""
        for request in self:
            request.assets_created_count = len(request.asset_ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Generate purchase request reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.purchase.request"
                ) or "New"
        return super().create(vals_list)

    def action_submit(self):
        """Submit the purchase request for approval."""
        for request in self:
            if not request.category_id:
                raise UserError("Please select an asset category.")
            if request.quantity < 1:
                raise UserError("Quantity must be at least 1.")
            if not request.supplier_id:
                raise UserError("Please select a supplier.")
            request.state = "submitted"

    def action_approve(self):
        """Approve the purchase request."""
        self.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Datetime.now(),
        })

    def action_reject(self):
        """Reject the purchase request (opens wizard)."""
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.purchase.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_purchase_request_id": self.id},
        }

    def action_create_purchase_order(self):
        """Create a Purchase Order from the approved request."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError("Only approved purchase requests can create Purchase Orders.")
        if not self.supplier_id:
            raise UserError("Please select a supplier before creating a Purchase Order.")

        # Get or create a default product for asset purchases
        product = self._get_asset_purchase_product()

        # Create the Purchase Order
        po_vals = {
            "partner_id": self.supplier_id.id,
            "date_order": fields.Datetime.now(),
            "assetz_purchase_request_id": self.id,
            "order_line": [(0, 0, {
                "product_id": product.id,
                "name": f"{self.category_id.name} - {self.description or 'Asset Purchase'}",
                "product_qty": self.quantity,
                "price_unit": self.estimated_unit_cost or 0.0,
                "date_planned": self.needed_by_date or fields.Date.today(),
            })],
        }

        purchase_order = self.env["purchase.order"].create(po_vals)

        self.write({
            "purchase_order_id": purchase_order.id,
            "state": "po_created",
        })

        # Return action to view the created PO
        return {
            "type": "ir.actions.act_window",
            "name": "Purchase Order",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": purchase_order.id,
        }

    def _get_asset_purchase_product(self):
        """Get or create the default product for asset purchases."""
        # Check if there's a configured product
        config_product_id = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.default_asset_purchase_product_id"
        )
        if config_product_id:
            product = self.env["product.product"].browse(int(config_product_id))
            if product.exists():
                return product

        # Search for existing asset purchase product
        product = self.env["product.product"].search([
            ("default_code", "=", "ASSET-PURCHASE"),
        ], limit=1)

        if not product:
            # Create a default product for asset purchases
            product = self.env["product.product"].create({
                "name": "Asset Purchase",
                "default_code": "ASSET-PURCHASE",
                "type": "service",
                "purchase_ok": True,
                "sale_ok": False,
            })

        return product

    def action_receive_and_create_assets(self):
        """Called when PO is received - creates assets based on configuration."""
        self.ensure_one()
        if self.state != "po_created":
            raise UserError("Purchase Order must be created first.")

        # Check configuration for auto-create
        auto_create = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.auto_create_assets_from_po", "False"
        ) == "True"

        if auto_create:
            self._auto_create_assets()
            self.state = "received"
            # Update source asset request to assets_ready state (not fulfilled yet)
            if self.asset_request_id:
                self.asset_request_id.state = "assets_ready"
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Assets Created",
                    "message": f"{self.quantity} asset(s) have been created. You can now issue them from the Asset Request.",
                    "type": "success",
                },
            }
        else:
            # Open wizard for manual asset creation
            return {
                "type": "ir.actions.act_window",
                "name": "Create Assets",
                "res_model": "assetz.create.assets.wizard",
                "view_mode": "form",
                "target": "new",
                "context": {"default_purchase_request_id": self.id},
            }

    def _auto_create_assets(self):
        """Auto-create assets when PO received."""
        self.ensure_one()

        # Get the unit cost from PO if available
        unit_cost = self.estimated_unit_cost
        if self.purchase_order_id and self.purchase_order_id.order_line:
            unit_cost = self.purchase_order_id.order_line[0].price_unit

        created_assets = self.env["assetz.asset"]
        for i in range(self.quantity):
            asset_vals = {
                "name": f"{self.category_id.name} - {self.name} #{i + 1}",
                "category_id": self.category_id.id,
                "supplier_id": self.supplier_id.id,
                "acquisition_date": fields.Date.today(),
                "acquisition_cost": unit_cost,
                "purchase_request_id": self.id,
                "state": "draft",
            }
            # Link to source asset request if available
            if self.asset_request_id:
                asset_vals["source_asset_request_id"] = self.asset_request_id.id
            asset = self.env["assetz.asset"].create(asset_vals)
            created_assets |= asset

        return created_assets

    def _on_po_received(self):
        """Callback when the Purchase Order is received."""
        self.ensure_one()
        # Check configuration for auto-create
        auto_create = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.auto_create_assets_from_po", "False"
        ) == "True"

        if auto_create:
            self._auto_create_assets()
            self.state = "received"
            # Update source asset request to assets_ready state (not fulfilled yet)
            if self.asset_request_id:
                self.asset_request_id.state = "assets_ready"

    def action_cancel(self):
        """Cancel the purchase request."""
        for request in self:
            if request.state == "po_created" and request.purchase_order_id:
                if request.purchase_order_id.state not in ("draft", "cancel"):
                    raise UserError(
                        "Cannot cancel purchase request - the Purchase Order is already confirmed. "
                        "Please cancel the Purchase Order first."
                    )
            request.state = "cancelled"

    def action_draft(self):
        """Reset to draft state."""
        self.write({"state": "draft"})

    def action_view_assets(self):
        """View the assets created from this purchase request."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Created Assets",
            "res_model": "assetz.asset",
            "view_mode": "list,form",
            "domain": [("purchase_request_id", "=", self.id)],
        }

    def action_view_purchase_order(self):
        """View the linked Purchase Order."""
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError("No Purchase Order linked to this request.")
        return {
            "type": "ir.actions.act_window",
            "name": "Purchase Order",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": self.purchase_order_id.id,
        }


class AssetPurchaseRequestRejectWizard(models.TransientModel):
    """Wizard for rejecting purchase requests with reason."""

    _name = "assetz.purchase.request.reject.wizard"
    _description = "Purchase Request Rejection Wizard"

    purchase_request_id = fields.Many2one(
        comodel_name="assetz.purchase.request",
        string="Purchase Request",
        required=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        """Reject the request with the provided reason."""
        self.purchase_request_id.write({
            "state": "cancelled",
            "rejection_reason": self.reason,
        })
        return {"type": "ir.actions.act_window_close"}
