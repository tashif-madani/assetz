from odoo import api, fields, models
from odoo.exceptions import UserError


class ProjectTask(models.Model):
    """Extend the FSM task (project.task with is_fsm=True) with an Assetz job
    lifecycle: Mobilisation → In Progress → Completed → Demobilisation →
    Closed. Modelled after the IWS pattern (see
    /Users/macos/dev/git/odoo/iws_dev/IWS/integrated_wellhead_services/
    models/sale_order.py — IWS puts the same selection on sale.order; we
    put it on project.task because in assetz the FSM task IS the job).

    Outward + Inward stock pickings are auto-created on order confirm and
    linked back via stock.picking.assetz_job_id. Mobilisation forces the
    outward picking to Done; Demobilisation forces the inward picking to
    Done — the same `_validate_picking` shortcut IWS uses.
    """

    _inherit = "project.task"

    # ----- Asset + order context fields -------------------------------------

    asset_id = fields.Many2one(
        "assetz.asset",
        string="Asset",
        help="The physical asset this task is for (set automatically when "
        "the task is spawned from an Assetz sale order).",
    )

    # Surface the agreement on the task too (related — read-only).
    assetz_agreement_id = fields.Many2one(
        related="sale_order_id.agreement_id",
        string="Agreement",
        readonly=True,
    )

    # Related sale.order state — drives freeze-on-confirm logic for the task.
    assetz_order_state = fields.Selection(
        related="sale_order_id.state",
        string="Order State",
        readonly=True,
    )

    # Convenience flag for view conditions.
    is_assetz_job = fields.Boolean(
        compute="_compute_is_assetz_job",
        store=False,
    )

    # ----- Technicians (hr.employee, not res.users) -------------------------

    # The standard project.task.user_ids is a Many2many to res.users (login
    # users). For Assetz jobs the customer-relevant assignee is the
    # technician — an hr.employee. We expose a separate Many2many so the
    # FSM screen and our reports can pick from the employee catalogue.
    assetz_technician_ids = fields.Many2many(
        "hr.employee",
        "assetz_task_technician_rel",
        "task_id",
        "employee_id",
        string="Technicians",
        help="Employees (from hr.employee) assigned to perform this job.",
    )

    # ----- Job lifecycle ----------------------------------------------------

    assetz_job_status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("mobilisation", "Mobilisation"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("demobilisation", "Demobilisation"),
            ("closed", "Closed"),
        ],
        string="Job Status",
        default="pending",
        tracking=True,
        copy=False,
    )

    assetz_mobilised_date = fields.Datetime(readonly=True, copy=False)
    assetz_completed_date = fields.Datetime(readonly=True, copy=False)
    assetz_demobilised_date = fields.Datetime(readonly=True, copy=False)
    assetz_closed_date = fields.Datetime(readonly=True, copy=False)

    # ----- Deliveries -------------------------------------------------------

    assetz_delivery_ids = fields.One2many(
        "stock.picking",
        "assetz_job_id",
        string="Deliveries",
    )
    assetz_delivery_count = fields.Integer(
        compute="_compute_assetz_delivery_count",
    )

    @api.depends("sale_order_id", "sale_order_id.is_assetz_order")
    def _compute_is_assetz_job(self):
        for task in self:
            task.is_assetz_job = bool(
                task.sale_order_id and task.sale_order_id.is_assetz_order
            )

    @api.depends("assetz_delivery_ids")
    def _compute_assetz_delivery_count(self):
        for task in self:
            task.assetz_delivery_count = len(task.assetz_delivery_ids)

    # ----- Picking validation helper ----------------------------------------

    def _assetz_validate_picking(self, picking):
        """Force a stock.picking to 'done' state, bypassing all intermediate
        wizards. Mirrors IWS's `_validate_picking` (job.py).

        Uses the Odoo 18 stock API: write the qty directly onto each move
        and flip `picked=True`, then call `_action_done` with the right
        context flags to skip sanity/backorder/SMS prompts.
        """
        if not picking or picking.state in ("done", "cancel"):
            return
        if picking.state == "confirmed":
            picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(
            skip_sanity_check=True,
            skip_backorder=True,
            skip_sms=True,
            picking_ids_not_to_backorder=picking.ids,
        )._action_done()

    # ----- Workflow buttons -------------------------------------------------

    def action_assetz_start_mobilisation(self):
        for task in self:
            if task.assetz_job_status != "pending":
                raise UserError("Only a pending job can start mobilisation.")
            outward = task.assetz_delivery_ids.filtered(
                lambda p: p.assetz_transfer_type == "outward"
            )
            for p in outward:
                task._assetz_validate_picking(p)
            task.assetz_job_status = "mobilisation"
            task.assetz_mobilised_date = fields.Datetime.now()

    def action_assetz_in_progress(self):
        for task in self:
            if task.assetz_job_status != "mobilisation":
                raise UserError("Mobilise the job before moving it In Progress.")
            task.assetz_job_status = "in_progress"

    def action_assetz_complete(self):
        for task in self:
            if task.assetz_job_status != "in_progress":
                raise UserError("Only an in-progress job can be completed.")
            task.assetz_job_status = "completed"
            task.assetz_completed_date = fields.Datetime.now()

    def action_assetz_demobilise(self):
        for task in self:
            if task.assetz_job_status != "completed":
                raise UserError("Complete the job before demobilising.")
            inward = task.assetz_delivery_ids.filtered(
                lambda p: p.assetz_transfer_type == "inward"
            )
            for p in inward:
                task._assetz_validate_picking(p)
            task.assetz_job_status = "demobilisation"
            task.assetz_demobilised_date = fields.Datetime.now()

    def action_assetz_close(self):
        for task in self:
            if task.assetz_job_status != "demobilisation":
                raise UserError("Demobilise the job before closing it.")
            task.assetz_job_status = "closed"
            task.assetz_closed_date = fields.Datetime.now()

    # ----- Smart button: deliveries -----------------------------------------

    def action_view_assetz_deliveries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Deliveries — {self.name}",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("assetz_job_id", "=", self.id)],
            "context": {"search_default_group_assetz_transfer_type": 1},
        }
