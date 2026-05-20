from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class AssetzMaintenanceOrder(models.Model):
    """Standalone maintenance order for Assetz assets."""

    _name = "assetz.maintenance.order"
    _description = "Maintenance Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_date desc, priority desc, id desc"

    # === Basic Information ===
    name = fields.Char(
        string="Order Reference",
        required=True,
        copy=False,
        readonly=True,
        default="New",
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
        tracking=True,
        index=True,
    )
    asset_code = fields.Char(
        related="asset_id.code",
        string="Asset Code",
        store=True,
    )
    category_id = fields.Many2one(
        related="asset_id.category_id",
        string="Asset Category",
        store=True,
    )
    location_id = fields.Many2one(
        related="asset_id.location_id",
        string="Location",
        store=True,
    )

    # === Maintenance Type ===
    maintenance_type = fields.Selection(
        selection=[
            ("preventive", "Preventive"),
            ("corrective", "Corrective"),
            ("inspection", "Inspection"),
            ("emergency", "Emergency"),
        ],
        string="Maintenance Type",
        required=True,
        default="corrective",
        tracking=True,
    )
    schedule_id = fields.Many2one(
        comodel_name="assetz.maintenance.schedule",
        string="Schedule",
        help="Linked preventive maintenance schedule",
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
        tracking=True,
    )
    color = fields.Integer(string="Color Index", compute="_compute_color")

    # === State Management ===
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("in_progress", "In Progress"),
            ("pending_parts", "Pending Parts"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )

    # === Scheduling ===
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.today,
        tracking=True,
    )
    scheduled_date = fields.Date(
        string="Scheduled Date",
        tracking=True,
        index=True,
    )
    deadline_date = fields.Date(
        string="Deadline",
        tracking=True,
    )
    actual_start = fields.Datetime(
        string="Actual Start",
        tracking=True,
    )
    actual_end = fields.Datetime(
        string="Actual End",
        tracking=True,
    )
    duration_hours = fields.Float(
        string="Duration (Hours)",
        compute="_compute_duration",
        store=True,
    )

    # === Assignment ===
    technician_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Technician",
        tracking=True,
    )
    team_id = fields.Many2one(
        comodel_name="assetz.maintenance.team",
        string="Maintenance Team",
        tracking=True,
    )
    requested_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        tracking=True,
    )

    # === Corrective Maintenance Details ===
    issue_reported = fields.Text(
        string="Issue Reported",
        help="Description of the problem or issue",
    )
    failure_type = fields.Selection(
        selection=[
            ("mechanical", "Mechanical"),
            ("electrical", "Electrical"),
            ("software", "Software/Firmware"),
            ("wear", "Normal Wear"),
            ("damage", "Physical Damage"),
            ("calibration", "Calibration"),
            ("other", "Other"),
        ],
        string="Failure Type",
    )
    root_cause = fields.Text(
        string="Root Cause Analysis",
        help="Analysis of why the issue occurred",
    )
    resolution = fields.Text(
        string="Resolution",
        help="Description of how the issue was resolved",
    )

    # === Checklist ===
    checklist_template_id = fields.Many2one(
        comodel_name="assetz.checklist.template",
        string="Checklist Template",
    )
    checklist_line_ids = fields.One2many(
        comodel_name="assetz.maintenance.checklist.line",
        inverse_name="order_id",
        string="Checklist Items",
        copy=False,
    )
    checklist_progress = fields.Float(
        string="Checklist Progress",
        compute="_compute_checklist_progress",
        store=True,
    )
    checklist_result = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("passed", "Passed"),
            ("failed", "Failed"),
            ("partial", "Partial Pass"),
        ],
        string="Checklist Result",
        compute="_compute_checklist_progress",
        store=True,
    )
    checklist_total_items = fields.Integer(
        compute="_compute_checklist_progress",
        store=True,
    )
    checklist_completed_items = fields.Integer(
        compute="_compute_checklist_progress",
        store=True,
    )
    checklist_passed_items = fields.Integer(
        compute="_compute_checklist_progress",
        store=True,
    )
    checklist_failed_items = fields.Integer(
        compute="_compute_checklist_progress",
        store=True,
    )

    # === Parts & Labor ===
    parts_line_ids = fields.One2many(
        comodel_name="assetz.maintenance.parts.line",
        inverse_name="order_id",
        string="Parts Used",
    )
    labor_line_ids = fields.One2many(
        comodel_name="assetz.maintenance.labor.line",
        inverse_name="order_id",
        string="Labor",
    )
    parts_cost = fields.Monetary(
        string="Parts Cost",
        compute="_compute_costs",
        store=True,
        currency_field="currency_id",
    )
    labor_cost = fields.Monetary(
        string="Labor Cost",
        compute="_compute_costs",
        store=True,
        currency_field="currency_id",
    )
    total_cost = fields.Monetary(
        string="Total Cost",
        compute="_compute_costs",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # === Signatures ===
    technician_signature = fields.Binary(
        string="Technician Signature",
    )
    technician_signed_by = fields.Many2one(
        comodel_name="hr.employee",
        string="Signed By (Technician)",
    )
    technician_signed_date = fields.Datetime(
        string="Technician Sign Date",
    )
    customer_signature = fields.Binary(
        string="Customer/Manager Signature",
    )
    customer_signed_name = fields.Char(
        string="Customer/Manager Name",
    )
    customer_signed_date = fields.Datetime(
        string="Customer Sign Date",
    )
    is_technician_signed = fields.Boolean(
        compute="_compute_signature_status",
    )
    is_customer_signed = fields.Boolean(
        compute="_compute_signature_status",
    )

    # === Contract Integration ===
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        help="Customer to bill for non-covered work",
    )
    # Alias for backwards compatibility
    customer_id = fields.Many2one(
        related="partner_id",
        string="Customer (Alias)",
    )
    contract_id = fields.Many2one(
        comodel_name="assetz.service.contract",
        string="Service Contract",
    )
    has_active_contract = fields.Boolean(
        string="Has Active Contract",
        compute="_compute_contract_status",
        store=True,
    )
    warranty_status = fields.Selection(
        selection=[
            ("no_contract", "No Contract"),
            ("under_warranty", "Under Warranty"),
            ("under_amc", "Under AMC"),
            ("expired", "Expired"),
        ],
        string="Warranty Status",
        compute="_compute_contract_status",
        store=True,
    )
    billing_status = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("covered", "Fully Covered"),
            ("partially_covered", "Partially Covered"),
            ("bill_customer", "Bill Customer"),
            ("internal", "Internal Cost"),
        ],
        string="Billing Status",
        default="pending",
        tracking=True,
    )

    # === Notes ===
    description = fields.Text(
        string="Description",
    )
    internal_notes = fields.Text(
        string="Internal Notes",
    )
    customer_notes = fields.Text(
        string="Notes for Customer",
    )

    # === Company ===
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # === SQL Constraints ===
    _sql_constraints = [
        (
            "name_uniq",
            "unique(name, company_id)",
            "Order reference must be unique per company!",
        ),
    ]

    # === Computed Methods ===

    @api.depends("priority")
    def _compute_color(self):
        """Compute color based on priority."""
        color_map = {"0": 0, "1": 3, "2": 2, "3": 1}
        for order in self:
            order.color = color_map.get(order.priority, 0)

    @api.depends("actual_start", "actual_end")
    def _compute_duration(self):
        """Compute actual duration in hours."""
        for order in self:
            if order.actual_start and order.actual_end:
                delta = order.actual_end - order.actual_start
                order.duration_hours = delta.total_seconds() / 3600
            else:
                order.duration_hours = 0.0

    @api.depends(
        "checklist_line_ids",
        "checklist_line_ids.is_completed",
        "checklist_line_ids.is_passed",
    )
    def _compute_checklist_progress(self):
        """Compute checklist completion progress and result."""
        for order in self:
            lines = order.checklist_line_ids
            total = len(lines)
            completed = len(lines.filtered(lambda l: l.is_completed))
            passed = len(lines.filtered(lambda l: l.is_completed and l.is_passed))
            failed = len(lines.filtered(lambda l: l.is_completed and not l.is_passed))

            order.checklist_total_items = total
            order.checklist_completed_items = completed
            order.checklist_passed_items = passed
            order.checklist_failed_items = failed
            order.checklist_progress = (completed / total * 100) if total else 0.0

            # Determine result
            if total == 0:
                order.checklist_result = "pending"
            elif completed < total:
                order.checklist_result = "pending"
            elif failed == 0:
                order.checklist_result = "passed"
            elif passed == 0:
                order.checklist_result = "failed"
            else:
                order.checklist_result = "partial"

    @api.depends("parts_line_ids.amount", "labor_line_ids.amount")
    def _compute_costs(self):
        """Compute total costs from parts and labor."""
        for order in self:
            order.parts_cost = sum(order.parts_line_ids.mapped("amount"))
            order.labor_cost = sum(order.labor_line_ids.mapped("amount"))
            order.total_cost = order.parts_cost + order.labor_cost

    @api.depends("technician_signature", "customer_signature")
    def _compute_signature_status(self):
        """Check if signatures are present."""
        for order in self:
            order.is_technician_signed = bool(order.technician_signature)
            order.is_customer_signed = bool(order.customer_signature)

    @api.depends("asset_id", "asset_id.contract_ids")
    def _compute_contract_status(self):
        """Find active contracts for the linked asset."""
        for order in self:
            if not order.asset_id:
                order.has_active_contract = False
                order.warranty_status = "no_contract"
                continue

            asset = order.asset_id
            contracts = self.env["assetz.service.contract"].search(
                [
                    ("state", "=", "active"),
                    ("is_valid", "=", True),
                    "|",
                    ("asset_ids", "in", asset.id),
                    "&",
                    ("apply_to_category", "=", True),
                    ("category_id", "=", asset.category_id.id),
                ]
            )

            order.has_active_contract = bool(contracts)

            if not contracts:
                order.warranty_status = "no_contract"
            else:
                contract_types = contracts.mapped("contract_type")
                if (
                    "manufacturer_warranty" in contract_types
                    or "extended_warranty" in contract_types
                ):
                    order.warranty_status = "under_warranty"
                elif "amc" in contract_types or "service_agreement" in contract_types:
                    order.warranty_status = "under_amc"
                else:
                    order.warranty_status = "no_contract"

    # === CRUD Methods ===

    @api.model_create_multi
    def create(self, vals_list):
        """Generate order reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("assetz.maintenance.order")
                    or "New"
                )
        return super().create(vals_list)

    # === Action Methods ===

    def action_schedule(self):
        """Schedule the maintenance order."""
        for order in self:
            if order.state != "draft":
                raise UserError("Only draft orders can be scheduled.")
            if not order.scheduled_date:
                raise UserError("Please set a scheduled date before scheduling.")
            order.state = "scheduled"

    def action_start(self):
        """Start working on the maintenance order."""
        for order in self:
            if order.state not in ("draft", "scheduled"):
                raise UserError("Order must be in draft or scheduled state to start.")
            order.write(
                {
                    "state": "in_progress",
                    "actual_start": fields.Datetime.now(),
                }
            )
            # Update asset state if needed
            if order.asset_id.state == "active":
                order.asset_id.state = "maintenance"

    def action_pending_parts(self):
        """Mark order as waiting for parts."""
        for order in self:
            if order.state != "in_progress":
                raise UserError("Only in-progress orders can be set to pending parts.")
            order.state = "pending_parts"

    def action_resume(self):
        """Resume work after parts received."""
        for order in self:
            if order.state != "pending_parts":
                raise UserError("Only pending parts orders can be resumed.")
            order.state = "in_progress"

    def action_complete(self):
        """Complete the maintenance order."""
        for order in self:
            if order.state not in ("in_progress", "pending_parts"):
                raise UserError("Order must be in progress to complete.")

            # Validate required checklist items
            required_incomplete = order.checklist_line_ids.filtered(
                lambda l: l.is_required and not l.is_completed
            )
            if required_incomplete:
                raise ValidationError(
                    f"Please complete all required checklist items before completing. "
                    f"Missing: {', '.join(required_incomplete.mapped('name'))}"
                )

            order.write(
                {
                    "state": "completed",
                    "actual_end": fields.Datetime.now(),
                }
            )

            # Update asset state back to active
            if order.asset_id.state == "maintenance":
                order.asset_id.state = "active"

            # Update schedule if linked
            if order.schedule_id:
                order.schedule_id._update_after_completion(order)

            # Update asset last maintenance date
            order.asset_id.last_maintenance_date = fields.Date.today()

    def action_cancel(self):
        """Cancel the maintenance order."""
        for order in self:
            if order.state == "completed":
                raise UserError("Completed orders cannot be cancelled.")
            # Restore asset state if it was put in maintenance
            if order.asset_id.state == "maintenance":
                order.asset_id.state = "active"
            order.state = "cancelled"

    def action_draft(self):
        """Reset to draft state."""
        for order in self:
            if order.state not in ("cancelled", "scheduled"):
                raise UserError("Only cancelled or scheduled orders can be reset to draft.")
            order.state = "draft"

    def action_create_checklist(self):
        """Open wizard to create checklist from template."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Create Checklist",
            "res_model": "assetz.create.checklist.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_asset_id": self.asset_id.id,
            },
        }

    def action_ai_suggest_checklist(self):
        """Open AI wizard to generate checklist based on asset."""
        self.ensure_one()
        if not self.asset_id:
            raise UserError("Please select an asset before using AI suggestions.")
        return {
            "type": "ir.actions.act_window",
            "name": "AI Checklist Suggestions",
            "res_model": "assetz.ai.checklist.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_asset_id": self.asset_id.id,
                "default_maintenance_type": self.maintenance_type,
                "default_category_ids": [(6, 0, [self.category_id.id])]
                if self.category_id
                else [],
            },
        }

    def action_apply_checklist_template(self):
        """Apply the selected checklist template."""
        self.ensure_one()
        if not self.checklist_template_id:
            raise UserError("Please select a checklist template first.")

        # Clear existing checklist lines
        self.checklist_line_ids.unlink()

        # Create new lines from template
        for template_line in self.checklist_template_id.line_ids:
            self.env["assetz.maintenance.checklist.line"].create(
                {
                    "order_id": self.id,
                    "sequence": template_line.sequence,
                    "name": template_line.name,
                    "description": template_line.description,
                    "check_type": template_line.check_type,
                    "group_name": template_line.group_name,
                    "expected_min": template_line.expected_min,
                    "expected_max": template_line.expected_max,
                    "unit": template_line.unit,
                    "selection_options": template_line.selection_options,
                    "is_required": template_line.is_required,
                    "requires_photo": template_line.requires_photo,
                    "requires_notes": template_line.requires_notes,
                }
            )

        return True

    def action_sign_technician(self):
        """Open signature wizard for technician."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Technician Signature",
            "res_model": "assetz.signature.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_signature_type": "technician",
            },
        }

    def action_sign_customer(self):
        """Open signature wizard for customer."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Customer/Manager Signature",
            "res_model": "assetz.signature.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
                "default_signature_type": "customer",
            },
        }

    def action_print_work_order(self):
        """Print Work Order Summary report."""
        self.ensure_one()
        return self.env.ref(
            "assetz.action_report_maintenance_work_order"
        ).report_action(self)

    def action_print_checklist(self):
        """Print Checklist Report."""
        self.ensure_one()
        return self.env.ref(
            "assetz.action_report_maintenance_checklist"
        ).report_action(self)

    def action_print_certificate(self):
        """Print Service Certificate."""
        self.ensure_one()
        if self.state != "completed":
            raise UserError("Certificate can only be printed for completed orders.")
        return self.env.ref(
            "assetz.action_report_maintenance_certificate"
        ).report_action(self)

    def action_open_schedule_wizard(self):
        """Open technician scheduling wizard."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Schedule Technicians",
            "res_model": "assetz.technician.schedule.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_order_id": self.id,
            },
        }


class AssetzMaintenanceChecklistLine(models.Model):
    """Checklist line item with actual readings."""

    _name = "assetz.maintenance.checklist.line"
    _description = "Maintenance Checklist Line"
    _order = "sequence, id"

    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)

    # === Item Definition ===
    name = fields.Char(string="Check Item", required=True)
    description = fields.Text(string="Instructions")
    check_type = fields.Selection(
        selection=[
            ("boolean", "Pass/Fail"),
            ("reading", "Numeric Reading"),
            ("text", "Text Entry"),
            ("selection", "Selection"),
            ("photo", "Photo Only"),
        ],
        string="Check Type",
        required=True,
        default="boolean",
    )
    group_name = fields.Char(string="Section/Group")

    # === Expected Values ===
    expected_min = fields.Float(string="Min Value")
    expected_max = fields.Float(string="Max Value")
    unit = fields.Char(string="Unit")
    selection_options = fields.Char(
        string="Options",
        help="Comma-separated options",
    )

    # === Requirements ===
    is_required = fields.Boolean(string="Required", default=True)
    requires_photo = fields.Boolean(string="Photo Required")
    requires_notes = fields.Boolean(string="Notes Required")

    # === Actual Values ===
    result = fields.Selection(
        selection=[
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("na", "N/A"),
        ],
        string="Result",
    )
    value_numeric = fields.Float(string="Reading")
    value_text = fields.Text(string="Text Value")
    value_selection = fields.Char(string="Selected Option")
    photo_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="maintenance_checklist_line_photo_rel",
        column1="line_id",
        column2="attachment_id",
        string="Photos",
    )
    notes = fields.Text(string="Notes")

    # === Completion Tracking ===
    is_completed = fields.Boolean(
        string="Completed",
        compute="_compute_status",
        store=True,
    )
    is_passed = fields.Boolean(
        string="Passed",
        compute="_compute_status",
        store=True,
    )
    is_within_range = fields.Boolean(
        string="Within Range",
        compute="_compute_status",
        store=True,
    )
    completed_by_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Completed By",
    )
    completed_at = fields.Datetime(string="Completed At")

    @api.depends(
        "check_type",
        "result",
        "value_numeric",
        "value_text",
        "value_selection",
        "photo_ids",
        "expected_min",
        "expected_max",
        "requires_photo",
        "requires_notes",
        "notes",
    )
    def _compute_status(self):
        """Compute completion and pass/fail status."""
        for line in self:
            completed = False
            passed = True
            within_range = True

            if line.check_type == "boolean":
                completed = line.result in ("pass", "fail", "na")
                passed = line.result in ("pass", "na")

            elif line.check_type == "reading":
                completed = line.value_numeric is not None and line.value_numeric != 0
                # Check if within expected range
                if completed and (line.expected_min or line.expected_max):
                    if line.expected_min and line.value_numeric < line.expected_min:
                        within_range = False
                    if line.expected_max and line.value_numeric > line.expected_max:
                        within_range = False
                    passed = within_range
                # If no range specified, reading itself is considered pass
                elif completed:
                    passed = True

            elif line.check_type == "text":
                completed = bool(line.value_text)
                passed = completed

            elif line.check_type == "selection":
                completed = bool(line.value_selection)
                passed = completed

            elif line.check_type == "photo":
                completed = bool(line.photo_ids)
                passed = completed

            # Check photo requirement
            if line.requires_photo and not line.photo_ids:
                completed = False

            # Check notes requirement
            if line.requires_notes and not line.notes:
                completed = False

            line.is_completed = completed
            line.is_passed = passed
            line.is_within_range = within_range

    @api.onchange("result", "value_numeric", "value_text", "value_selection")
    def _onchange_value(self):
        """Set completion timestamp when value changes."""
        if self.is_completed and not self.completed_at:
            self.completed_at = fields.Datetime.now()
            # Try to get current user's employee
            employee = self.env["hr.employee"].search(
                [("user_id", "=", self.env.uid)], limit=1
            )
            if employee:
                self.completed_by_id = employee.id


class AssetzMaintenancePartsLine(models.Model):
    """Parts/materials used in a maintenance order."""

    _name = "assetz.maintenance.parts.line"
    _description = "Maintenance Parts Line"
    _order = "sequence, id"

    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)

    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Part",
        domain="[('type', 'in', ['product', 'consu'])]",
    )
    description = fields.Char(
        string="Description",
        required=True,
    )
    quantity = fields.Float(
        string="Quantity",
        default=1.0,
    )
    unit_cost = fields.Monetary(
        string="Unit Cost",
        currency_field="currency_id",
    )
    amount = fields.Monetary(
        string="Total",
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
    )

    @api.depends("quantity", "unit_cost")
    def _compute_amount(self):
        """Calculate line total."""
        for line in self:
            line.amount = line.quantity * line.unit_cost

    @api.onchange("product_id")
    def _onchange_product_id(self):
        """Auto-fill description and cost from product."""
        if self.product_id:
            self.description = self.product_id.name
            self.unit_cost = self.product_id.standard_price


class AssetzMaintenanceLaborLine(models.Model):
    """Labor hours logged for a maintenance order."""

    _name = "assetz.maintenance.labor.line"
    _description = "Maintenance Labor Line"
    _order = "sequence, id"

    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)

    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Technician",
    )
    description = fields.Char(
        string="Description",
        required=True,
    )
    date = fields.Date(
        string="Date",
        default=fields.Date.today,
    )
    hours = fields.Float(
        string="Hours",
        default=1.0,
    )
    hourly_rate = fields.Monetary(
        string="Hourly Rate",
        currency_field="currency_id",
    )
    amount = fields.Monetary(
        string="Total",
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="order_id.currency_id",
    )

    @api.depends("hours", "hourly_rate")
    def _compute_amount(self):
        """Calculate line total."""
        for line in self:
            line.amount = line.hours * line.hourly_rate

    @api.model
    def default_get(self, fields_list):
        """Set default hourly rate from settings."""
        res = super().default_get(fields_list)
        if "hourly_rate" in fields_list:
            default_rate = float(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("assetz.default_labor_rate", "50.0")
            )
            res["hourly_rate"] = default_rate
        return res
