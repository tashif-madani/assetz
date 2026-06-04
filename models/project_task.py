from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


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

    # Stable job number separate from the sale.order's reference. Assigned
    # automatically on creation for Assetz jobs (parent tasks only; sub-tasks
    # share their parent's job number via the related field below).
    assetz_job_number = fields.Char(
        string="Job Number",
        copy=False,
        readonly=True,
        index=True,
        help="Stable JOB/<year>/##### identifier for field crew reference.",
    )

    # Per-task equipment (filtered to non-service products). A flat
    # Many2many is enough — the heavier qty/source tracking lives on the
    # parent order's assetz.order.equipment table.
    assetz_equipment_ids = fields.Many2many(
        "product.product",
        "assetz_task_equipment_rel",
        "task_id",
        "product_id",
        string="Equipment",
        domain="[('type', '!=', 'service')]",
        help="Equipment items needed to perform this specific task / sub-task.",
    )

    # IWS-style task structure: each service spawns a section-header row
    # (display_type='line_section') + 5 regular rows ("Task 1"…"Task 5").
    # display_type is a custom field on project.task — Odoo standard
    # doesn't add it.
    display_type = fields.Selection(
        selection=[("line_section", "Section")],
        copy=False,
        default=False,
        help="When 'line_section', this row is shown as a section header in "
             "the Tasks list — no work fields, just a visual grouping.",
    )

    # Bookend tasks: an Arrival task at the very start of every job, and a
    # Departure task at the very end. They behave like normal tasks but
    # can't be moved or deleted by the user.
    assetz_is_arrival = fields.Boolean(default=False, copy=False)
    assetz_is_departure = fields.Boolean(default=False, copy=False)

    # Per-task start / end datetimes for field crew scheduling.
    assetz_task_start_dt = fields.Datetime(
        string="Start",
        copy=False,
        help="When this task begins on site (stamped by the Start button).",
    )
    assetz_task_end_dt = fields.Datetime(
        string="End",
        copy=False,
        help="When this task ends on site (stamped by the End button).",
    )

    # Per-task status — independent of project.task.stage_id (kanban). The
    # Start / End buttons in the Tasks list drive this. Mirrors IWS's
    # `iws_task_status`.
    assetz_task_status = fields.Selection(
        selection=[
            ("new", "New"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
        ],
        string="Task Status",
        default="new",
        copy=False,
        tracking=True,
    )

    # Total hours between start and end (read-only, recomputes).
    assetz_total_hours = fields.Float(
        string="Hours",
        compute="_compute_assetz_total_hours",
        store=True,
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

    # ----- Swap (move up / down) flags --------------------------------------
    # The Tasks list is reordered with explicit up/down buttons, not drag.
    # These drive button visibility per row.
    assetz_can_swap_up = fields.Boolean(compute="_compute_assetz_swap_flags")
    assetz_can_swap_down = fields.Boolean(compute="_compute_assetz_swap_flags")

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

    # ----- Reordering by swap buttons (no drag) -----------------------------

    def _assetz_service_groups(self, job):
        """Break a job's task rows into ordered service groups.

        Returns a list of {'header': section-row or False, 'tasks': [task rows]}
        in display order. Arrive/Leave bookends are excluded — they're fixed.
        Each section header starts a new group; the regular task rows that
        follow it (until the next header) are its tasks.
        """
        groups = []
        current = None
        for rec in job.child_ids.sorted(key=lambda t: (t.sequence, t.id)):
            if rec.assetz_is_arrival or rec.assetz_is_departure:
                continue
            if rec.display_type == "line_section":
                current = {"header": rec, "tasks": []}
                groups.append(current)
            else:
                if current is None:
                    current = {"header": False, "tasks": []}
                    groups.append(current)
                current["tasks"].append(rec)
        return groups

    @api.depends(
        "sequence", "display_type", "assetz_is_arrival", "assetz_is_departure",
        "assetz_task_status",
        "parent_id", "parent_id.child_ids", "parent_id.child_ids.sequence",
        "parent_id.child_ids.display_type", "parent_id.child_ids.assetz_task_status",
    )
    def _compute_assetz_swap_flags(self):
        for task in self:
            up = down = False
            job = task.parent_id
            if job and not task.assetz_is_arrival and not task.assetz_is_departure:
                groups = task._assetz_service_groups(job)
                if task.display_type == "line_section":
                    # A section swaps as a whole block with an adjacent section.
                    headers = [g["header"] for g in groups if g["header"]]
                    if task in headers:
                        i = headers.index(task)
                        up = i > 0
                        down = i < len(headers) - 1
                elif task.assetz_task_status != "done":
                    # A not-done task swaps only with the OTHER not-done tasks
                    # inside its service. Completed tasks are pinned at the top
                    # of the service and have no swap buttons at all.
                    for g in groups:
                        if task in g["tasks"]:
                            movable = [
                                t for t in g["tasks"]
                                if t.assetz_task_status != "done"
                            ]
                            i = movable.index(task)
                            up = i > 0
                            down = i < len(movable) - 1
                            break
            task.assetz_can_swap_up = up
            task.assetz_can_swap_down = down

    def action_assetz_swap_up(self):
        self.ensure_one()
        self._assetz_swap("up")

    def action_assetz_swap_down(self):
        self.ensure_one()
        self._assetz_swap("down")

    def _assetz_swap(self, direction):
        """Move this row one step up/down. Arrive/Leave never move. A section
        header carries its whole block and swaps with the adjacent service.
        A task swaps only with its neighbour inside the same service.
        """
        self.ensure_one()
        if self.assetz_is_arrival or self.assetz_is_departure:
            raise UserError("Arrive at Location and Leave Location can't be moved.")
        job = self.parent_id
        if not job:
            return
        groups = self._assetz_service_groups(job)

        if self.display_type == "line_section":
            sections = [g for g in groups if g["header"]]
            headers = [g["header"] for g in sections]
            if self not in headers:
                return
            i = headers.index(self)
            j = i - 1 if direction == "up" else i + 1
            if 0 <= j < len(sections):
                upper, lower = (
                    (sections[j], sections[i]) if direction == "up"
                    else (sections[i], sections[j])
                )
                self._assetz_swap_blocks(upper, lower)
        else:
            # Completed tasks are pinned — never swappable.
            if self.assetz_task_status == "done":
                return
            for g in groups:
                if self in g["tasks"]:
                    # Swap only among the not-done tasks (the done ones sit
                    # locked at the top of the service).
                    movable = [
                        t for t in g["tasks"] if t.assetz_task_status != "done"
                    ]
                    i = movable.index(self)
                    j = i - 1 if direction == "up" else i + 1
                    if 0 <= j < len(movable):
                        other = movable[j]
                        s_seq, o_seq = self.sequence, other.sequence
                        self.sequence = o_seq
                        other.sequence = s_seq
                    break

    def _assetz_realign_done_to_top(self):
        """self = a task just completed. Re-stack its service so completed
        tasks sit at the top of that service (right under the section header),
        in completion order, with the not-done tasks keeping their order below.
        Only this one service block is touched — other services and the
        Arrive/Leave bookends are left exactly where they are.
        """
        self.ensure_one()
        job = self.parent_id
        if not job:
            return
        for g in self._assetz_service_groups(job):
            if self in g["tasks"]:
                tasks = g["tasks"]
                done = sorted(
                    (t for t in tasks if t.assetz_task_status == "done"),
                    key=lambda t: (t.assetz_task_end_dt or fields.Datetime.now(), t.id),
                )
                not_done = [t for t in tasks if t.assetz_task_status != "done"]
                # Reassign the service's own task slots: done first, then rest.
                slots = sorted(t.sequence for t in tasks)
                for rec, seq in zip(done + not_done, slots):
                    if rec.sequence != seq:
                        rec.sequence = seq
                break

    def _assetz_swap_blocks(self, group_a, group_b):
        """Swap two adjacent service blocks. group_a sits above group_b.
        Reassigns the combined sequence slots so group_b's rows come first.
        """
        rows_a = ([group_a["header"]] if group_a["header"] else []) + list(group_a["tasks"])
        rows_b = ([group_b["header"]] if group_b["header"] else []) + list(group_b["tasks"])
        rows_a.sort(key=lambda r: r.sequence)
        rows_b.sort(key=lambda r: r.sequence)
        slots = sorted(r.sequence for r in rows_a + rows_b)
        for rec, seq in zip(rows_b + rows_a, slots):
            if rec.sequence != seq:
                rec.sequence = seq

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

    # ----- Per-row Task list buttons ----------------------------------------

    @api.depends("assetz_task_start_dt", "assetz_task_end_dt")
    def _compute_assetz_total_hours(self):
        for task in self:
            if task.assetz_task_start_dt and task.assetz_task_end_dt:
                delta = task.assetz_task_end_dt - task.assetz_task_start_dt
                task.assetz_total_hours = delta.total_seconds() / 3600.0
            else:
                task.assetz_total_hours = 0.0

    def action_assetz_add_task_in_section(self):
        """Add a new task row right after this section's existing tasks.

        Picks a sequence between this section and the *next boundary*,
        where a "boundary" is either the next section OR the Leave
        Location departure task — whichever has the lower sequence.
        Names the new task "Task N" — N being the count of existing
        regular tasks already in this section + 1.
        """
        self.ensure_one()
        if self.display_type != "line_section":
            raise UserError("Add Task is only available on section rows.")
        parent_job = self.parent_id
        if not parent_job:
            raise UserError("Section row is missing its parent job.")

        # Upper bound: next section OR departure task, whichever comes first.
        boundary = self.search([
            ("parent_id", "=", parent_job.id),
            ("sequence", ">", self.sequence),
            "|",
            ("display_type", "=", "line_section"),
            ("assetz_is_departure", "=", True),
        ], order="sequence asc", limit=1)

        in_section_domain = [
            ("parent_id", "=", parent_job.id),
            ("sequence", ">", self.sequence),
            ("display_type", "!=", "line_section"),
            ("assetz_is_arrival", "=", False),
            ("assetz_is_departure", "=", False),
        ]
        if boundary:
            in_section_domain.append(("sequence", "<", boundary.sequence))

        existing_tasks = self.search(in_section_domain, order="sequence asc")
        new_seq = (existing_tasks[-1].sequence + 1) if existing_tasks else (self.sequence + 1)
        # Safety: never collide with or exceed the boundary
        if boundary and new_seq >= boundary.sequence:
            raise UserError(
                "No room for more tasks in this section without renumbering."
            )
        new_number = len(existing_tasks) + 1

        self.create({
            "name": f"Task {new_number}",
            "project_id": parent_job.project_id.id,
            "parent_id": parent_job.id,
            "sale_order_id": parent_job.sale_order_id.id,
            "partner_id": parent_job.partner_id.id,
            "company_id": parent_job.company_id.id,
            "sequence": new_seq,
            "user_ids": [(5,)],
        })

    @api.constrains("sequence", "assetz_is_arrival", "assetz_is_departure")
    def _assetz_check_bookend_position(self):
        """Hard-lock the Arrive at Location / Leave Location bookends.

        If the user (or drag-drop) somehow tries to reorder them, this
        constraint fires and rolls the change back. Arrival must always
        have the lowest sequence among its siblings; Departure the highest.

        Skips the check when there are no siblings yet — that's the
        normal state during initial creation (Arrival is created before
        the service sections / Departure exist).
        """
        for rec in self:
            if not (rec.assetz_is_arrival or rec.assetz_is_departure):
                continue
            if not rec.parent_id:
                continue
            siblings = self.search([
                ("parent_id", "=", rec.parent_id.id),
                ("id", "!=", rec.id),
            ])
            if not siblings:
                continue
            sib_seqs = siblings.mapped("sequence")
            if rec.assetz_is_arrival and min(sib_seqs) <= rec.sequence:
                raise ValidationError(
                    "Arrive at Location must remain at the top of the Tasks list."
                )
            if rec.assetz_is_departure and max(sib_seqs) >= rec.sequence:
                raise ValidationError(
                    "Leave Location must remain at the bottom of the Tasks list."
                )

    def action_assetz_delete_task(self):
        """Custom delete — refuses to remove arrival/departure or done rows."""
        for task in self:
            if task.assetz_is_arrival or task.assetz_is_departure:
                raise UserError("Arrival and Departure tasks can't be deleted.")
            if task.assetz_task_status == "done":
                raise UserError("Completed tasks can't be deleted.")
        self.unlink()

    def action_assetz_start_task(self):
        """Open the datetime-picker wizard for the Start time of this task."""
        self.ensure_one()
        if self.display_type == "line_section":
            raise UserError("Section rows can't be started.")
        if self.assetz_task_status != "new":
            raise UserError("Only a 'new' task can be started.")
        return self._assetz_open_time_wizard("start")

    def action_assetz_end_task(self):
        """Open the datetime-picker wizard for the End time of this task."""
        self.ensure_one()
        if self.display_type == "line_section":
            raise UserError("Section rows can't be ended.")
        if self.assetz_task_status != "in_progress":
            raise UserError("Only an in-progress task can be ended.")
        return self._assetz_open_time_wizard("end")

    def _assetz_open_time_wizard(self, action_type):
        return {
            "type": "ir.actions.act_window",
            "name": "Start" if action_type == "start" else "End",
            "res_model": "assetz.task.time.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_task_id": self.id,
                "default_action_type": action_type,
            },
        }

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
