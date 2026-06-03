from odoo import fields, models


class StockPicking(models.Model):
    """Back-link from a stock transfer to the Assetz FSM job that owns it.

    Matches the IWS pattern (`iws_job_id` + `iws_transfer_type` — see
    /Users/macos/dev/git/odoo/iws_dev/IWS/integrated_wellhead_services/
    models/stock_picking.py). Outward goes Warehouse → Customer; inward
    is the return trip Customer → Warehouse.
    """

    _inherit = "stock.picking"

    assetz_job_id = fields.Many2one(
        "project.task",
        string="Assetz Job",
        index=True,
        copy=False,
        help="The Assetz FSM job this transfer belongs to.",
    )
    assetz_transfer_type = fields.Selection(
        selection=[
            ("outward", "Outward (to Customer)"),
            ("inward", "Inward (from Customer)"),
        ],
        string="Assetz Transfer Type",
        copy=False,
    )
