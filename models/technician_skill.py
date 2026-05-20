from datetime import timedelta

from odoo import api, fields, models


class AssetzTechnicianSkill(models.Model):
    """Skills/competencies for technicians in maintenance operations."""

    _name = "assetz.technician.skill"
    _description = "Technician Skill"
    _order = "name"

    name = fields.Char(
        string="Skill Name",
        required=True,
    )
    description = fields.Text(
        string="Description",
    )
    category_ids = fields.Many2many(
        comodel_name="assetz.category",
        relation="technician_skill_category_rel",
        column1="skill_id",
        column2="category_id",
        string="Applicable Asset Categories",
        help="Categories where this skill is relevant",
    )
    active = fields.Boolean(
        default=True,
    )

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Skill name must be unique!"),
    ]


class AssetzTechnicianSkillLine(models.Model):
    """Assignment of skills to employees with proficiency levels."""

    _name = "assetz.technician.skill.line"
    _description = "Technician Skill Assignment"
    _order = "employee_id, skill_id"

    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
        index=True,
    )
    skill_id = fields.Many2one(
        comodel_name="assetz.technician.skill",
        string="Skill",
        required=True,
        ondelete="cascade",
        index=True,
    )
    proficiency = fields.Selection(
        selection=[
            ("beginner", "Beginner"),
            ("intermediate", "Intermediate"),
            ("expert", "Expert"),
        ],
        string="Proficiency Level",
        default="beginner",
        required=True,
    )
    certified = fields.Boolean(
        string="Certified",
        help="Has formal certification for this skill",
    )
    certification_expiry = fields.Date(
        string="Certification Expiry",
        help="When the certification expires",
    )
    notes = fields.Text(
        string="Notes",
    )

    _sql_constraints = [
        (
            "employee_skill_uniq",
            "unique(employee_id, skill_id)",
            "An employee can only have one proficiency level per skill!",
        ),
    ]


class HrEmployeeTechnician(models.Model):
    """Extend hr.employee with technician-specific fields."""

    _inherit = "hr.employee"

    # === Technician Status ===
    is_technician = fields.Boolean(
        string="Is Technician",
        help="Mark this employee as available for maintenance scheduling",
    )

    # === Skills ===
    skill_line_ids = fields.One2many(
        comodel_name="assetz.technician.skill.line",
        inverse_name="employee_id",
        string="Skills",
    )
    skill_ids = fields.Many2many(
        comodel_name="assetz.technician.skill",
        string="Skills Summary",
        compute="_compute_skill_ids",
        store=True,
    )

    # === Scheduling Parameters ===
    max_daily_hours = fields.Float(
        string="Max Daily Hours",
        default=8.0,
        help="Maximum schedulable hours per day",
    )
    default_location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Base Location",
        help="Default location for proximity calculations",
    )
    default_hourly_rate = fields.Float(
        string="Default Hourly Rate",
        help="Default hourly rate for labor calculations",
    )

    # === Workload Statistics (Computed) ===
    scheduled_order_count = fields.Integer(
        string="Scheduled Orders",
        compute="_compute_workload",
        help="Number of orders in scheduled state",
    )
    in_progress_order_count = fields.Integer(
        string="In Progress Orders",
        compute="_compute_workload",
        help="Number of orders currently in progress",
    )
    total_scheduled_hours = fields.Float(
        string="Scheduled Hours (Week)",
        compute="_compute_workload",
        help="Total labor hours scheduled this week",
    )

    @api.depends("skill_line_ids", "skill_line_ids.skill_id")
    def _compute_skill_ids(self):
        """Compute all skills for an employee."""
        for employee in self:
            employee.skill_ids = employee.skill_line_ids.mapped("skill_id")

    def _compute_workload(self):
        """Compute current workload statistics."""
        MaintenanceOrder = self.env["assetz.maintenance.order"]
        LaborLine = self.env["assetz.maintenance.labor.line"]

        # Get current week boundaries
        today = fields.Date.today()
        weekday = today.weekday()
        week_start = today - timedelta(days=weekday)
        week_end = week_start + timedelta(days=6)

        for employee in self:
            # Count orders by state where employee is technician
            employee.scheduled_order_count = MaintenanceOrder.search_count(
                [
                    ("technician_id", "=", employee.id),
                    ("state", "=", "scheduled"),
                ]
            )
            employee.in_progress_order_count = MaintenanceOrder.search_count(
                [
                    ("technician_id", "=", employee.id),
                    ("state", "=", "in_progress"),
                ]
            )

            # Sum labor hours for this week
            labor_lines = LaborLine.search(
                [
                    ("employee_id", "=", employee.id),
                    ("date", ">=", week_start),
                    ("date", "<=", week_end),
                ]
            )
            employee.total_scheduled_hours = sum(labor_lines.mapped("hours"))

    def get_available_hours_on_date(self, date):
        """Calculate available hours for a technician on a specific date.

        Args:
            date: The date to check availability

        Returns:
            float: Available hours on that date
        """
        self.ensure_one()

        # Get labor lines for this date
        labor_lines = self.env["assetz.maintenance.labor.line"].search(
            [
                ("employee_id", "=", self.id),
                ("date", "=", date),
            ]
        )
        used_hours = sum(labor_lines.mapped("hours"))

        # Available = max daily hours - used hours (default to 8 if not set)
        max_hours = self.max_daily_hours or 8.0
        available = max_hours - used_hours
        return max(0.0, available)

    def get_orders_on_date(self, date):
        """Get maintenance orders assigned to this technician on a specific date.

        Args:
            date: The date to check

        Returns:
            recordset: Maintenance orders scheduled for that date
        """
        self.ensure_one()
        return self.env["assetz.maintenance.order"].search(
            [
                ("technician_id", "=", self.id),
                ("scheduled_date", "=", date),
                ("state", "not in", ("completed", "cancelled")),
            ]
        )

    def get_skill_match_score(self, category_id):
        """Calculate skill match score for an asset category.

        Args:
            category_id: The asset category to match against

        Returns:
            tuple: (score_percentage, has_required_skills)
        """
        self.ensure_one()

        if not category_id:
            return 100, True  # No category = no skill requirement

        # Get skills applicable to this category
        required_skills = self.env["assetz.technician.skill"].search(
            [("category_ids", "in", [category_id])]
        )

        if not required_skills:
            return 100, True  # No skills defined for category

        # Check employee's skills against required skills
        employee_skill_lines = self.skill_line_ids.filtered(
            lambda l: l.skill_id in required_skills
        )

        if not employee_skill_lines:
            return 0, False  # No matching skills

        # Calculate score based on proficiency
        proficiency_weights = {
            "beginner": 1,
            "intermediate": 2,
            "expert": 3,
        }

        max_possible_score = len(required_skills) * 3  # All expert level
        actual_score = sum(
            proficiency_weights.get(line.proficiency, 0)
            for line in employee_skill_lines
        )

        score_percentage = int((actual_score / max_possible_score) * 100)
        has_required = len(employee_skill_lines) == len(required_skills)

        return score_percentage, has_required
