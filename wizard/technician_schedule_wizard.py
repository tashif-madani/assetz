import json
import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TechnicianScheduleWizard(models.TransientModel):
    """Wizard for scheduling technicians to maintenance orders."""

    _name = "assetz.technician.schedule.wizard"
    _description = "Technician Schedule Wizard"

    # === State Management ===
    state = fields.Selection(
        selection=[
            ("select", "Select Technicians"),
            ("preview", "Preview Labor Lines"),
        ],
        string="State",
        default="select",
    )

    # === Context from Maintenance Order ===
    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
    )
    order_name = fields.Char(
        related="order_id.name",
        string="Order Reference",
    )
    asset_id = fields.Many2one(
        related="order_id.asset_id",
        string="Asset",
    )
    asset_category_id = fields.Many2one(
        related="order_id.category_id",
        string="Asset Category",
    )
    asset_location_id = fields.Many2one(
        related="order_id.location_id",
        string="Asset Location",
    )
    scheduled_date = fields.Date(
        related="order_id.scheduled_date",
        string="Scheduled Date",
    )
    maintenance_type = fields.Selection(
        related="order_id.maintenance_type",
        string="Maintenance Type",
    )
    team_id = fields.Many2one(
        related="order_id.team_id",
        string="Maintenance Team",
    )

    # === Date Range for Calendar Grid ===
    date_from = fields.Date(
        string="From Date",
        default=fields.Date.today,
    )
    date_to = fields.Date(
        string="To Date",
        default=lambda self: fields.Date.today() + timedelta(days=6),
    )

    # === Technician Lines ===
    technician_line_ids = fields.One2many(
        comodel_name="assetz.technician.schedule.wizard.line",
        inverse_name="wizard_id",
        string="Technicians",
    )

    # === AI Recommendations ===
    ai_recommendation = fields.Text(
        string="AI Recommendation",
        readonly=True,
    )
    ai_recommended_ids = fields.Many2many(
        comodel_name="hr.employee",
        relation="technician_schedule_ai_recommend_rel",
        string="AI Recommended",
    )

    # === Preview Labor Lines ===
    preview_labor_line_ids = fields.One2many(
        comodel_name="assetz.technician.schedule.wizard.labor.line",
        inverse_name="wizard_id",
        string="Labor Lines to Create",
    )

    @api.model
    def default_get(self, fields_list):
        """Set defaults from context."""
        res = super().default_get(fields_list)

        # Get order_id from context
        order_id = self.env.context.get("default_order_id")
        if order_id:
            # Explicitly set order_id so related fields work
            res["order_id"] = order_id

            # Also set non-related copies of key fields for immediate display
            order = self.env["assetz.maintenance.order"].browse(order_id)
            if order.exists():
                # Set date_from to scheduled date or today
                target_date = order.scheduled_date or fields.Date.today()
                res["date_from"] = target_date
                res["date_to"] = target_date + timedelta(days=6)

                # Load technicians automatically
                if "technician_line_ids" in fields_list:
                    res["technician_line_ids"] = self._prepare_technician_lines(
                        order, target_date
                    )

        return res

    def _prepare_technician_lines(self, order, target_date):
        """Prepare technician lines with availability data."""
        lines = []

        # Get all technicians (employees marked as is_technician=True)
        technicians = self.env["hr.employee"].search([("is_technician", "=", True)])

        # If team is specified, filter by team members
        if order.team_id and order.team_id.member_ids:
            team_members = order.team_id.member_ids
            team_technicians = technicians.filtered(lambda t: t in team_members)
            # Only apply filter if it results in some technicians
            if team_technicians:
                technicians = team_technicians

        for tech in technicians:
            # Calculate availability
            available_hours = tech.get_available_hours_on_date(target_date)
            orders_count = len(tech.get_orders_on_date(target_date))

            # Determine status
            if available_hours >= 4:
                status = "available"
            elif available_hours > 0:
                status = "partial"
            else:
                status = "busy"

            # Calculate skill match
            score, has_skills = tech.get_skill_match_score(order.category_id.id)

            # Build availability details for date range
            availability_details = self._build_availability_details(
                tech, target_date, target_date + timedelta(days=6)
            )

            lines.append(
                (
                    0,
                    0,
                    {
                        "employee_id": tech.id,
                        "selected": False,
                        "availability_status": status,
                        "available_hours": available_hours,
                        "scheduled_orders": orders_count,
                        "skill_match_score": score,
                        "has_required_skills": has_skills,
                        "availability_details": json.dumps(availability_details),
                    },
                )
            )

        return lines

    def _build_availability_details(self, employee, date_from, date_to):
        """Build daily availability data for the date range."""
        details = {}
        current_date = date_from

        while current_date <= date_to:
            available = employee.get_available_hours_on_date(current_date)
            orders = len(employee.get_orders_on_date(current_date))
            details[str(current_date)] = {
                "available_hours": available,
                "orders": orders,
                "status": "available"
                if available >= 4
                else ("partial" if available > 0 else "busy"),
            }
            current_date += timedelta(days=1)

        return details

    def action_refresh(self):
        """Refresh technician availability data."""
        self.ensure_one()

        # Clear existing lines
        self.technician_line_ids.unlink()

        # Recreate lines with current date range
        target_date = self.scheduled_date or self.date_from or fields.Date.today()
        lines = self._prepare_technician_lines(self.order_id, target_date)

        # Check if we found any technicians
        if not lines:
            raise UserError(
                "No technicians found. Please mark employees as technicians by:\n"
                "1. Go to Assetz → Configuration → Technicians\n"
                "2. Select an employee and check 'Is Technician' checkbox\n"
                "3. Return here and click 'Refresh Availability'"
            )

        # Create new lines
        for line_vals in lines:
            vals = line_vals[2].copy()  # Make a copy to avoid modifying original
            vals["wizard_id"] = self.id
            self.env["assetz.technician.schedule.wizard.line"].create(vals)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_ai_suggest(self):
        """Get AI recommendations for technician selection."""
        self.ensure_one()

        # Check if AI is enabled
        ai_enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.enable_ai_recommendations", "False")
        )
        if ai_enabled != "True":
            raise UserError(
                "AI Recommendations are not enabled. Please enable them in "
                "Settings > Assetz > AI Recommendations."
            )

        try:
            recommendations = self._call_ai_for_recommendations()
        except Exception as e:
            _logger.error(f"AI recommendation failed: {e}")
            raise UserError(f"AI recommendation failed: {str(e)}")

        if recommendations:
            # Update recommendation text
            self.ai_recommendation = recommendations.get("explanation", "")

            # Get recommended technician IDs
            recommended_ids = recommendations.get("recommended_ids", [])

            # Auto-select recommended technicians
            for line in self.technician_line_ids:
                if line.employee_id.id in recommended_ids:
                    line.selected = True

            # Store recommended IDs
            self.ai_recommended_ids = [(6, 0, recommended_ids)]

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _call_ai_for_recommendations(self):
        """Call the configured AI provider for technician recommendations."""
        ai_provider = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.ai_provider", "none")
        )

        if ai_provider == "openai":
            return self._call_openai_for_recommendations()
        elif ai_provider == "anthropic":
            return self._call_anthropic_for_recommendations()
        else:
            raise UserError(
                "No AI provider configured. Please select OpenAI or Anthropic "
                "in Settings > Assetz > AI Recommendations."
            )

    def _build_ai_prompt(self):
        """Build prompt for AI technician recommendations."""
        # Order details
        order = self.order_id
        order_info = f"""
Maintenance Order: {order.name}
Asset: {order.asset_id.name if order.asset_id else 'Not specified'}
Asset Category: {order.category_id.name if order.category_id else 'Not specified'}
Asset Location: {order.location_id.name if order.location_id else 'Not specified'}
Scheduled Date: {order.scheduled_date}
Maintenance Type: {order.maintenance_type}
Priority: {dict(order._fields['priority'].selection).get(order.priority, 'Medium')}
"""

        # Technician data
        technician_data = []
        for line in self.technician_line_ids:
            tech = line.employee_id
            tech_info = {
                "id": tech.id,
                "name": tech.name,
                "availability_status": line.availability_status,
                "available_hours": line.available_hours,
                "scheduled_orders_today": line.scheduled_orders,
                "skill_match_score": line.skill_match_score,
                "has_required_skills": line.has_required_skills,
                "total_weekly_hours": tech.total_scheduled_hours,
                "base_location": tech.default_location_id.name
                if tech.default_location_id
                else None,
            }
            technician_data.append(tech_info)

        prompt = f"""You are an expert maintenance scheduling system.
Recommend the best technicians for the following maintenance order.

{order_info}

Available Technicians:
{json.dumps(technician_data, indent=2)}

Selection Criteria (in order of importance):
1. Availability - Must have available hours on the scheduled date
2. Skills Match - Higher skill_match_score indicates better fit for asset category
3. Workload Balancing - Prefer technicians with lower total_weekly_hours
4. Location Proximity - Prefer technicians whose base_location matches asset location

Respond ONLY with valid JSON in this exact format:
{{
    "recommended_ids": [list of recommended technician IDs in order of preference],
    "explanation": "Brief explanation of why these technicians are recommended"
}}

Important:
- Only recommend technicians with availability_status "available" or "partial"
- Recommend 1-3 technicians maximum
- Prioritize skill match for specialized maintenance
- Consider workload distribution to avoid overloading technicians"""

        return prompt

    def _call_openai_for_recommendations(self):
        """Call OpenAI API for technician recommendations."""
        try:
            import openai
        except ImportError:
            raise UserError(
                "OpenAI library not installed. Please install with: pip install openai"
            )

        api_key = (
            self.env["ir.config_parameter"].sudo().get_param("assetz.openai_api_key")
        )
        if not api_key:
            raise UserError("OpenAI API key not configured in settings.")

        prompt = self._build_ai_prompt()

        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert maintenance scheduling system. "
                        "Always respond with valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1000,
            )

            result_text = response.choices[0].message.content.strip()
            _logger.info(f"OpenAI response received: {len(result_text)} chars")
            return json.loads(result_text)

        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            raise UserError("AI returned invalid response. Please try again.")
        except Exception as e:
            _logger.error(f"OpenAI API call failed: {e}")
            raise UserError(f"OpenAI API error: {str(e)}")

    def _call_anthropic_for_recommendations(self):
        """Call Anthropic Claude API for technician recommendations."""
        try:
            import anthropic
        except ImportError:
            raise UserError(
                "Anthropic library not installed. "
                "Please install with: pip install anthropic"
            )

        api_key = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.anthropic_api_key")
        )
        if not api_key:
            raise UserError("Anthropic API key not configured in settings.")

        prompt = self._build_ai_prompt()

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )

            result_text = response.content[0].text.strip()

            # Clean up potential markdown formatting
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
            if result_text.endswith("```"):
                result_text = result_text[:-3]

            _logger.info(f"Anthropic response received: {len(result_text)} chars")
            return json.loads(result_text.strip())

        except json.JSONDecodeError as e:
            _logger.error(f"Failed to parse Anthropic response as JSON: {e}")
            raise UserError("AI returned invalid response. Please try again.")
        except Exception as e:
            _logger.error(f"Anthropic API call failed: {e}")
            raise UserError(f"Anthropic API error: {str(e)}")

    def action_proceed_to_preview(self):
        """Proceed to preview state with selected technicians."""
        self.ensure_one()

        selected_lines = self.technician_line_ids.filtered("selected")
        if not selected_lines:
            raise UserError("Please select at least one technician.")

        # Clear existing preview lines
        self.preview_labor_line_ids.unlink()

        # Create preview labor lines for each selected technician
        target_date = self.scheduled_date or fields.Date.today()
        default_rate = float(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.default_labor_rate", "50.0")
        )

        for line in selected_lines:
            tech = line.employee_id
            hourly_rate = tech.default_hourly_rate or default_rate

            self.env["assetz.technician.schedule.wizard.labor.line"].create(
                {
                    "wizard_id": self.id,
                    "employee_id": tech.id,
                    "date": target_date,
                    "hours": min(4.0, line.available_hours),  # Default to 4 hours or available
                    "hourly_rate": hourly_rate,
                    "description": f"Maintenance work on {self.order_id.name}",
                }
            )

        self.state = "preview"

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_back(self):
        """Go back to select state."""
        self.ensure_one()
        self.state = "select"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_confirm(self):
        """Create labor lines and close wizard."""
        self.ensure_one()

        if not self.preview_labor_line_ids:
            raise UserError("No labor lines to create.")

        # Create actual labor lines on the maintenance order
        for preview_line in self.preview_labor_line_ids:
            self.env["assetz.maintenance.labor.line"].create(
                {
                    "order_id": self.order_id.id,
                    "employee_id": preview_line.employee_id.id,
                    "date": preview_line.date,
                    "hours": preview_line.hours,
                    "hourly_rate": preview_line.hourly_rate,
                    "description": preview_line.description,
                }
            )

        # If primary technician not set, set the first one
        if not self.order_id.technician_id and self.preview_labor_line_ids:
            self.order_id.technician_id = self.preview_labor_line_ids[0].employee_id

        # Return to maintenance order
        return {
            "type": "ir.actions.act_window",
            "res_model": "assetz.maintenance.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
            "target": "current",
        }


class TechnicianScheduleWizardLine(models.TransientModel):
    """Wizard line for technician availability display."""

    _name = "assetz.technician.schedule.wizard.line"
    _description = "Technician Schedule Wizard Line"
    _order = "skill_match_score desc, available_hours desc"

    wizard_id = fields.Many2one(
        comodel_name="assetz.technician.schedule.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Technician",
        required=True,
    )
    selected = fields.Boolean(
        string="Select",
        default=False,
    )

    # === Availability Info ===
    availability_status = fields.Selection(
        selection=[
            ("available", "Available"),
            ("partial", "Partially Available"),
            ("busy", "Busy"),
        ],
        string="Status",
    )
    available_hours = fields.Float(
        string="Available Hours",
    )
    scheduled_orders = fields.Integer(
        string="Orders Today",
    )

    # === Skill Match ===
    skill_match_score = fields.Integer(
        string="Skill Match %",
    )
    has_required_skills = fields.Boolean(
        string="Has Skills",
    )

    # === Detailed Availability (JSON for calendar display) ===
    availability_details = fields.Text(
        string="Availability Details",
        help="JSON object with daily availability data",
    )

    # === Display Helpers ===
    availability_badge = fields.Char(
        compute="_compute_display_helpers",
    )
    skill_badge = fields.Char(
        compute="_compute_display_helpers",
    )

    @api.depends("availability_status", "skill_match_score", "has_required_skills")
    def _compute_display_helpers(self):
        """Compute display badge text."""
        for line in self:
            # Availability badge
            status_map = {
                "available": "Available",
                "partial": "Partial",
                "busy": "Busy",
            }
            line.availability_badge = status_map.get(
                line.availability_status, "Unknown"
            )

            # Skill badge
            if line.has_required_skills:
                line.skill_badge = f"{line.skill_match_score}% Match"
            else:
                line.skill_badge = "Missing Skills"


class TechnicianScheduleWizardLaborLine(models.TransientModel):
    """Preview labor line for the wizard."""

    _name = "assetz.technician.schedule.wizard.labor.line"
    _description = "Technician Schedule Wizard Labor Line"

    wizard_id = fields.Many2one(
        comodel_name="assetz.technician.schedule.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Technician",
        required=True,
    )
    date = fields.Date(
        string="Date",
        required=True,
    )
    hours = fields.Float(
        string="Hours",
        default=4.0,
    )
    hourly_rate = fields.Monetary(
        string="Hourly Rate",
        currency_field="currency_id",
    )
    description = fields.Char(
        string="Description",
    )
    amount = fields.Monetary(
        string="Total",
        compute="_compute_amount",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends("hours", "hourly_rate")
    def _compute_amount(self):
        """Calculate line total."""
        for line in self:
            line.amount = line.hours * line.hourly_rate
