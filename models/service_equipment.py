from odoo import fields, models


class AssetzServiceEquipment(models.Model):
    """Bridge between a *service* product and the equipment products required
    to perform it. Lives on `product.template.assetz_equipment_line_ids`.

    When an Assetz order has the service product on a line, the equipment
    listed here is auto-added to the order's "Equipments" tab (which is
    backed by our dedicated `assetz.order.equipment` model — see
    `models/order_equipment.py`).
    """

    _name = "assetz.service.equipment"
    _description = "Equipment required for a service"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    service_product_tmpl_id = fields.Many2one(
        "product.template",
        string="Service",
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
        string="Quantity",
        default=1.0,
        required=True,
    )
    note = fields.Char(string="Note")
