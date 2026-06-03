from odoo import fields, models


class ProductTemplate(models.Model):
    """Extend product.template with the equipment-master link.

    Only meaningful when `type == 'service'` — the field is exposed on the
    Configuration → Services form.
    """

    _inherit = "product.template"

    assetz_equipment_line_ids = fields.One2many(
        "assetz.service.equipment",
        "service_product_tmpl_id",
        string="Required Equipment",
        help="Equipment products required to perform this service. Auto-added "
        "to the Equipments tab of any Assetz order that includes this service.",
    )
