from odoo import fields, models


class ProjectTask(models.Model):
    """Extend the standard project.task (used as an FSM task when
    is_fsm=True) with an asset link. This is the only Assetz-specific bit
    the task needs — everything else (state machine, assignment, time
    tracking, signature, billing) is provided by industry_fsm.
    """

    _inherit = "project.task"

    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        help="The physical asset this task is for (set automatically when "
        "the task is spawned from an Assetz sale order).",
    )

    sale_order_state = fields.Selection(
        related="sale_order_id.state",
        string="Sales Order Status",
        help="Status of the linked sales order. Used to lock the customer "
        "field once the order is confirmed.",
    )
