from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetzMaintenanceSchedule(models.Model):
    """Preventive maintenance schedule definition for assets."""

    _name = "assetz.maintenance.schedule"
    _description = "Maintenance Schedule"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, name"

    # === Basic Information ===
    name = fields.Char(
        string="Schedule Name",
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string="Code",
        copy=False,
        readonly=True,
        default="New",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(string="Sequence", default=10)
    description = fields.Text(string="Description")

    # === Schedule Type ===
    schedule_type = fields.Selection(
        selection=[
            ("time_based", "Time-Based"),
            ("usage_based", "Usage-Based"),
            ("hybrid", "Both (Time + Usage)"),
        ],
        string="Schedule Type",
        required=True,
        default="time_based",
        tracking=True,
    )

    # === Time-Based Scheduling ===
    interval_number = fields.Integer(
        string="Every",
        default=1,
        help="Frequency interval (e.g., every 3 months)",
    )
    interval_type = fields.Selection(
        selection=[
            ("days", "Day(s)"),
            ("weeks", "Week(s)"),
            ("months", "Month(s)"),
            ("quarters", "Quarter(s)"),
            ("years", "Year(s)"),
        ],
        string="Interval Unit",
        default="months",
    )

    # === Usage-Based Scheduling ===
    usage_metric = fields.Selection(
        selection=[
            ("hours", "Operating Hours"),
            ("mileage", "Mileage (km)"),
            ("cycles", "Cycles/Operations"),
            ("custom", "Custom Metric"),
        ],
        string="Usage Metric",
    )
    usage_threshold = fields.Float(
        string="Usage Threshold",
        help="Trigger maintenance when this usage increment is reached",
    )
    usage_unit = fields.Char(
        string="Usage Unit",
        help="Custom unit label (e.g., 'hrs', 'km', 'cycles')",
    )

    # === Asset/Category Assignment ===
    asset_ids = fields.Many2many(
        comodel_name="assetz.asset",
        relation="assetz_schedule_asset_rel",
        column1="schedule_id",
        column2="asset_id",
        string="Assigned Assets",
    )
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Asset Category",
        help="Apply to all assets in this category",
    )
    apply_to_category = fields.Boolean(
        string="Apply to Entire Category",
        default=False,
    )
    asset_count = fields.Integer(
        string="Asset Count",
        compute="_compute_asset_count",
    )

    # === Checklist Template ===
    checklist_template_id = fields.Many2one(
        comodel_name="assetz.checklist.template",
        string="Checklist Template",
        help="Default checklist template for maintenance orders",
    )

    # === Maintenance Configuration ===
    maintenance_type = fields.Selection(
        selection=[
            ("preventive", "Preventive"),
            ("inspection", "Inspection"),
        ],
        string="Maintenance Type",
        default="preventive",
    )
    default_technician_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Default Technician",
    )
    team_id = fields.Many2one(
        comodel_name="assetz.maintenance.team",
        string="Maintenance Team",
    )
    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Urgent"),
        ],
        string="Priority",
        default="1",
    )
    lead_days = fields.Integer(
        string="Lead Days",
        default=7,
        help="Days before due date to create maintenance order",
    )

    # === Tracking ===
    start_date = fields.Date(
        string="Start Date",
        default=fields.Date.today,
        help="Date from which the schedule becomes active",
    )
    last_order_date = fields.Date(
        string="Last Order Date",
        help="Date when last maintenance order was created",
    )
    next_order_date = fields.Date(
        string="Next Order Date",
        compute="_compute_next_order_date",
        store=True,
        help="Date when next maintenance order will be created",
    )

    # === Usage Tracking (per asset stored separately) ===
    last_usage_reading = fields.Float(
        string="Last Usage Reading",
        help="Usage reading at last maintenance (for single asset schedules)",
    )

    # === Generated Orders ===
    order_ids = fields.One2many(
        comodel_name="assetz.maintenance.order",
        inverse_name="schedule_id",
        string="Maintenance Orders",
    )
    order_count = fields.Integer(
        string="Order Count",
        compute="_compute_order_count",
    )
    pending_order_count = fields.Integer(
        string="Pending Orders",
        compute="_compute_order_count",
    )

    # === State ===
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("paused", "Paused"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    # === Company ===
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # === Computed Methods ===

    @api.depends("asset_ids", "category_id", "apply_to_category")
    def _compute_asset_count(self):
        """Count total assets covered by this schedule."""
        for schedule in self:
            if schedule.apply_to_category and schedule.category_id:
                count = self.env["assetz.asset"].search_count(
                    [
                        ("category_id", "=", schedule.category_id.id),
                        ("state", "in", ["active", "maintenance"]),
                    ]
                )
            else:
                count = len(schedule.asset_ids)
            schedule.asset_count = count

    @api.depends("order_ids", "order_ids.state")
    def _compute_order_count(self):
        """Count maintenance orders."""
        for schedule in self:
            orders = schedule.order_ids
            schedule.order_count = len(orders)
            schedule.pending_order_count = len(
                orders.filtered(lambda o: o.state not in ("completed", "cancelled"))
            )

    @api.depends(
        "schedule_type",
        "interval_number",
        "interval_type",
        "last_order_date",
        "start_date",
        "lead_days",
    )
    def _compute_next_order_date(self):
        """Compute next order creation date based on schedule."""
        for schedule in self:
            if schedule.schedule_type == "usage_based":
                # Usage-based schedules don't have a fixed next date
                schedule.next_order_date = False
                continue

            # Determine base date
            base_date = schedule.last_order_date or schedule.start_date
            if not base_date:
                schedule.next_order_date = False
                continue

            # Calculate next maintenance date
            interval = schedule.interval_number or 1
            if schedule.interval_type == "days":
                next_date = base_date + timedelta(days=interval)
            elif schedule.interval_type == "weeks":
                next_date = base_date + timedelta(weeks=interval)
            elif schedule.interval_type == "months":
                next_date = base_date + relativedelta(months=interval)
            elif schedule.interval_type == "quarters":
                next_date = base_date + relativedelta(months=interval * 3)
            elif schedule.interval_type == "years":
                next_date = base_date + relativedelta(years=interval)
            else:
                next_date = base_date + relativedelta(months=interval)

            # Subtract lead days for order creation date
            order_creation_date = next_date - timedelta(days=schedule.lead_days or 0)
            schedule.next_order_date = order_creation_date

    # === CRUD Methods ===

    @api.model_create_multi
    def create(self, vals_list):
        """Generate schedule code on creation."""
        for vals in vals_list:
            if vals.get("code", "New") == "New":
                vals["code"] = (
                    self.env["ir.sequence"].next_by_code("assetz.maintenance.schedule")
                    or "New"
                )
        return super().create(vals_list)

    # === Action Methods ===

    def action_activate(self):
        """Activate the schedule."""
        for schedule in self:
            if not schedule.asset_ids and not (
                schedule.apply_to_category and schedule.category_id
            ):
                raise UserError(
                    "Please assign assets or a category before activating the schedule."
                )
            schedule.state = "active"

    def action_pause(self):
        """Pause the schedule."""
        for schedule in self:
            schedule.state = "paused"

    def action_draft(self):
        """Reset to draft."""
        for schedule in self:
            schedule.state = "draft"

    def action_view_orders(self):
        """View generated maintenance orders."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Maintenance Orders",
            "res_model": "assetz.maintenance.order",
            "view_mode": "list,form",
            "domain": [("schedule_id", "=", self.id)],
            "context": {"default_schedule_id": self.id},
        }

    def action_view_assets(self):
        """View assets covered by this schedule."""
        self.ensure_one()
        assets = self._get_assets_for_schedule()
        return {
            "type": "ir.actions.act_window",
            "name": "Covered Assets",
            "res_model": "assetz.asset",
            "view_mode": "list,form",
            "domain": [("id", "in", assets.ids)],
        }

    def action_generate_orders(self):
        """Manually trigger order generation."""
        self.ensure_one()
        if self.state != "active":
            raise UserError("Schedule must be active to generate orders.")

        created_orders = self._generate_maintenance_orders()
        if created_orders:
            return {
                "type": "ir.actions.act_window",
                "name": "Generated Orders",
                "res_model": "assetz.maintenance.order",
                "view_mode": "list,form",
                "domain": [("id", "in", created_orders.ids)],
            }
        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "No Orders Created",
                    "message": "No maintenance orders were due for creation.",
                    "type": "info",
                },
            }

    # === Helper Methods ===

    def _get_assets_for_schedule(self):
        """Return all applicable assets for this schedule."""
        self.ensure_one()
        if self.apply_to_category and self.category_id:
            return self.env["assetz.asset"].search(
                [
                    ("category_id", "=", self.category_id.id),
                    ("state", "in", ["active", "maintenance"]),
                ]
            )
        return self.asset_ids.filtered(lambda a: a.state in ["active", "maintenance"])

    def _is_time_based_due(self, asset):
        """Check if time-based maintenance is due for an asset."""
        self.ensure_one()
        today = fields.Date.today()

        # Get last completed order date for this asset
        last_order = self.env["assetz.maintenance.order"].search(
            [
                ("schedule_id", "=", self.id),
                ("asset_id", "=", asset.id),
                ("state", "=", "completed"),
            ],
            order="actual_end desc",
            limit=1,
        )

        if last_order and last_order.actual_end:
            base_date = last_order.actual_end.date()
        else:
            base_date = self.start_date or today

        # Calculate next due date
        interval = self.interval_number or 1
        if self.interval_type == "days":
            next_due = base_date + timedelta(days=interval)
        elif self.interval_type == "weeks":
            next_due = base_date + timedelta(weeks=interval)
        elif self.interval_type == "months":
            next_due = base_date + relativedelta(months=interval)
        elif self.interval_type == "quarters":
            next_due = base_date + relativedelta(months=interval * 3)
        elif self.interval_type == "years":
            next_due = base_date + relativedelta(years=interval)
        else:
            next_due = base_date + relativedelta(months=interval)

        # Check if due within lead days
        trigger_date = next_due - timedelta(days=self.lead_days or 0)
        return today >= trigger_date

    def _is_usage_based_due(self, asset):
        """Check if usage-based maintenance is due for an asset."""
        self.ensure_one()

        if not self.usage_threshold:
            return False

        # Get current usage from asset
        if self.usage_metric == "hours":
            current_usage = asset.current_usage_hours or 0
        elif self.usage_metric == "mileage":
            current_usage = asset.current_usage_mileage or 0
        elif self.usage_metric == "cycles":
            current_usage = asset.current_usage_cycles or 0
        else:
            # Custom metric - would need extension
            return False

        # Get usage at last completed maintenance
        last_order = self.env["assetz.maintenance.order"].search(
            [
                ("schedule_id", "=", self.id),
                ("asset_id", "=", asset.id),
                ("state", "=", "completed"),
            ],
            order="actual_end desc",
            limit=1,
        )

        if last_order:
            # Would need to store usage reading at completion
            # For now, use last_usage_reading on schedule
            last_usage = self.last_usage_reading or 0
        else:
            last_usage = 0

        # Check if usage delta exceeds threshold
        return (current_usage - last_usage) >= self.usage_threshold

    def _has_pending_order(self, asset):
        """Check if there's already a pending order for this asset."""
        return bool(
            self.env["assetz.maintenance.order"].search(
                [
                    ("schedule_id", "=", self.id),
                    ("asset_id", "=", asset.id),
                    ("state", "not in", ("completed", "cancelled")),
                ],
                limit=1,
            )
        )

    def _create_order_for_asset(self, asset):
        """Create a maintenance order for an asset."""
        self.ensure_one()

        # Calculate scheduled date
        today = fields.Date.today()
        if self.schedule_type in ("time_based", "hybrid"):
            scheduled_date = today + timedelta(days=self.lead_days or 7)
        else:
            scheduled_date = today

        # Create the order
        order = self.env["assetz.maintenance.order"].create(
            {
                "asset_id": asset.id,
                "maintenance_type": self.maintenance_type,
                "schedule_id": self.id,
                "priority": self.priority,
                "scheduled_date": scheduled_date,
                "technician_id": self.default_technician_id.id,
                "team_id": self.team_id.id if self.team_id else False,
                "checklist_template_id": self.checklist_template_id.id
                if self.checklist_template_id
                else False,
                "description": f"Scheduled {self.maintenance_type} maintenance: {self.name}",
            }
        )

        # Apply checklist template if set
        if self.checklist_template_id:
            order.action_apply_checklist_template()

        return order

    def _generate_maintenance_orders(self):
        """Generate maintenance orders for assets that are due."""
        self.ensure_one()
        created_orders = self.env["assetz.maintenance.order"]

        assets = self._get_assets_for_schedule()

        for asset in assets:
            # Skip if pending order exists
            if self._has_pending_order(asset):
                continue

            is_due = False

            if self.schedule_type == "time_based":
                is_due = self._is_time_based_due(asset)
            elif self.schedule_type == "usage_based":
                is_due = self._is_usage_based_due(asset)
            elif self.schedule_type == "hybrid":
                # Due if either condition is met
                is_due = self._is_time_based_due(asset) or self._is_usage_based_due(
                    asset
                )

            if is_due:
                order = self._create_order_for_asset(asset)
                created_orders |= order

        # Update last order date
        if created_orders:
            self.last_order_date = fields.Date.today()

        return created_orders

    def _update_after_completion(self, order):
        """Update schedule tracking after order completion."""
        self.ensure_one()

        # Update usage reading if usage-based
        if self.schedule_type in ("usage_based", "hybrid"):
            asset = order.asset_id
            if self.usage_metric == "hours":
                self.last_usage_reading = asset.current_usage_hours or 0
            elif self.usage_metric == "mileage":
                self.last_usage_reading = asset.current_usage_mileage or 0
            elif self.usage_metric == "cycles":
                self.last_usage_reading = asset.current_usage_cycles or 0

    # === Cron Methods ===

    @api.model
    def _cron_check_maintenance_due(self):
        """Cron job to check and generate maintenance orders."""
        active_schedules = self.search([("state", "=", "active")])

        for schedule in active_schedules:
            try:
                schedule._generate_maintenance_orders()
            except Exception as e:
                # Log error but continue with other schedules
                self.env.cr.rollback()
                self.env["mail.mail"].create(
                    {
                        "subject": f"Maintenance Schedule Error: {schedule.name}",
                        "body_html": f"<p>Error generating orders for schedule {schedule.name}: {str(e)}</p>",
                        "email_to": self.env.user.email,
                    }
                )
                self.env.cr.commit()
