from odoo import api, fields, models


class PurchaseOrder(models.Model):
    """Extend Purchase Order to link with Asset Purchase Requests."""

    _inherit = "purchase.order"

    assetz_purchase_request_id = fields.Many2one(
        comodel_name="assetz.purchase.request",
        string="Asset Purchase Request",
        readonly=True,
    )
    is_asset_purchase = fields.Boolean(
        string="Is Asset Purchase",
        compute="_compute_is_asset_purchase",
        store=True,
    )

    @api.depends("assetz_purchase_request_id")
    def _compute_is_asset_purchase(self):
        """Check if this PO is for asset purchase."""
        for order in self:
            order.is_asset_purchase = bool(order.assetz_purchase_request_id)

    def button_confirm(self):
        """Override to update linked purchase request state."""
        res = super().button_confirm()
        for order in self.filtered(lambda o: o.assetz_purchase_request_id):
            if order.assetz_purchase_request_id.state == "approved":
                order.assetz_purchase_request_id.state = "po_created"
        return res


class StockPicking(models.Model):
    """Extend Stock Picking to trigger asset creation on receipt."""

    _inherit = "stock.picking"

    def button_validate(self):
        """Override to trigger asset creation when PO is received."""
        res = super().button_validate()

        # For asset purchase POs, trigger asset creation
        for picking in self:
            if picking.picking_type_code == "incoming" and picking.purchase_id:
                purchase_request = picking.purchase_id.assetz_purchase_request_id
                if purchase_request and purchase_request.state == "po_created":
                    purchase_request._on_po_received()

        return res
