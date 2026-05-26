from odoo import fields, models


class ResCompany(models.Model):
    """Per-company storage for Assetz order feature toggles.

    Stored here (not in ir.config_parameter) so order forms can reach them
    via related fields — that loads fresh on every record read instead of
    going through a cached compute.
    """

    _inherit = "res.company"

    assetz_enable_agreements = fields.Boolean(
        string="Assetz — Enable Agreements on Orders",
        default=False,
    )
    assetz_enable_service_types_service = fields.Boolean(
        string="Assetz — Service Types on Service Orders",
        default=False,
    )
    assetz_enable_service_types_rental = fields.Boolean(
        string="Assetz — Service Types on Rental Orders",
        default=False,
    )
