from odoo import api, fields, models


class AssetzOrderEquipment(models.Model):
    """Equipment line attached to an Assetz sale order.

    Dedicated model (not sale.order.option) so we fully own the lifecycle:
    add / remove / edit qty / freeze on confirm without fighting
    sale_management's quoting flow.

    Lines fall into two camps:
      - auto-added from a service's required-equipment master
        (`assetz_auto_added=True`, with the source service stored)
      - manually added by the user (`assetz_auto_added=False`)

    The onchange on sale.order drops + recreates the auto-added rows
    whenever order_line changes; manual rows are never touched.
    """

    _name = "assetz.order.equipment"
    _description = "Assetz Order Equipment Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    order_id = fields.Many2one(
        "sale.order",
        string="Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    equipment_id = fields.Many2one(
        "product.product",
        string="Equipment",
        domain="[('type', '!=', 'service')]",
        required=True,
    )
    quantity = fields.Float(
        string="Qty",
        default=1.0,
        required=True,
    )
    note = fields.Char(string="Note")

    # Lifecycle tracking — set automatically by sale.order's onchange.
    assetz_auto_added = fields.Boolean(
        string="Auto-added",
        default=False,
        copy=False,
        help="Set when this line was created automatically from a service "
             "product's required-equipment master. Recomputed whenever the "
             "order's service lines change.",
    )
    assetz_source_service_product_id = fields.Many2one(
        "product.product",
        string="Source Service",
        copy=False,
        help="The service product whose master spawned this line — used to "
             "push back qty edits to the master.",
    )

    # Related state for view readonly logic (matches sale.order.state).
    order_state = fields.Selection(related="order_id.state", store=False, readonly=True)
    company_id = fields.Many2one(related="order_id.company_id", store=True, readonly=True)

    def write(self, vals):
        """Sync qty changes back to the source service's equipment master,
        as long as:
          - we know which service spawned this row,
          - the order is still in an editable state (draft / sent).
        """
        if "quantity" in vals:
            Bridge = self.env["assetz.service.equipment"]
            for rec in self:
                if not (
                    rec.assetz_source_service_product_id
                    and rec.equipment_id
                    and rec.order_id.state in ("draft", "sent")
                ):
                    continue
                bridge = Bridge.search([
                    ("service_product_tmpl_id", "=",
                     rec.assetz_source_service_product_id.product_tmpl_id.id),
                    ("equipment_id", "=", rec.equipment_id.id),
                ], limit=1)
                if bridge and bridge.quantity != vals["quantity"]:
                    bridge.quantity = vals["quantity"]
        return super().write(vals)

    @api.onchange("equipment_id")
    def _onchange_equipment_id(self):
        if self.equipment_id and not self.note:
            self.note = self.equipment_id.display_name
