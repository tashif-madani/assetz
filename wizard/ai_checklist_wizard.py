import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AIChecklistWizard(models.TransientModel):
    """Wizard for AI-powered checklist recommendations."""

    _name = "assetz.ai.checklist.wizard"
    _description = "AI Checklist Recommendation Wizard"

    # === State ===
    state = fields.Selection(
        selection=[
            ("input", "Input"),
            ("preview", "Preview Recommendations"),
        ],
        string="State",
        default="input",
    )

    # === Input Fields ===
    template_id = fields.Many2one(
        comodel_name="assetz.checklist.template",
        string="Checklist Template",
        help="The template to add items to",
    )
    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        help="The maintenance order to add checklist items to",
    )
    category_ids = fields.Many2many(
        comodel_name="assetz.category",
        relation="ai_checklist_wizard_category_rel",
        string="Asset Categories",
        help="Select categories to get relevant checklist recommendations",
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset/Equipment",
        help="Select a specific asset to get tailored checklist recommendations",
    )
    maintenance_type = fields.Selection(
        selection=[
            ("preventive", "Preventive Maintenance"),
            ("corrective", "Corrective Maintenance"),
            ("inspection", "Inspection"),
            ("calibration", "Calibration"),
            ("general", "General"),
        ],
        string="Maintenance Type",
        required=True,
        default="preventive",
    )
    asset_description = fields.Text(
        string="Asset/Equipment Description",
        help="Describe the type of asset or equipment (e.g., 'Industrial HVAC system', "
        "'CNC Milling Machine', 'Forklift')",
    )
    additional_context = fields.Text(
        string="Additional Context",
        help="Any specific requirements, standards, or focus areas "
        "(e.g., 'Focus on safety checks', 'Include lubrication points')",
    )

    # === AI Response ===
    recommended_items = fields.Text(
        string="AI Response",
        readonly=True,
    )

    # === Preview Lines ===
    preview_line_ids = fields.One2many(
        comodel_name="assetz.ai.checklist.wizard.line",
        inverse_name="wizard_id",
        string="Recommended Items",
    )

    @api.model
    def default_get(self, fields_list):
        """Set defaults from context."""
        res = super().default_get(fields_list)
        if self.env.context.get("active_model") == "assetz.checklist.template":
            template_id = self.env.context.get("active_id")
            if template_id:
                template = self.env["assetz.checklist.template"].browse(template_id)
                res["template_id"] = template_id
                res["maintenance_type"] = template.maintenance_type
                if template.category_ids:
                    res["category_ids"] = [(6, 0, template.category_ids.ids)]
        return res

    def action_get_recommendations(self):
        """Call AI to get checklist recommendations."""
        self.ensure_one()

        # Validate inputs
        if not self.category_ids and not self.asset_id and not self.asset_description:
            raise UserError(
                "Please select a category, asset, or provide an asset description."
            )

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

        # Call AI provider
        try:
            recommendations = self._call_ai_for_recommendations()
        except Exception as e:
            _logger.error(f"AI recommendation failed: {e}")
            raise UserError(f"AI recommendation failed: {str(e)}")

        # Clear existing preview lines
        self.preview_line_ids.unlink()

        # Parse and create preview lines
        if recommendations and "checklist_items" in recommendations:
            for idx, item in enumerate(recommendations["checklist_items"]):
                self._create_preview_line(item, idx + 1)

        if not self.preview_line_ids:
            raise UserError(
                "AI could not generate checklist recommendations. Please try with "
                "more specific asset description or different categories."
            )

        self.state = "preview"

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _call_ai_for_recommendations(self):
        """Call the configured AI provider."""
        ai_provider = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.ai_provider", "none")
        )

        if ai_provider == "openai":
            return self._call_openai()
        elif ai_provider == "anthropic":
            return self._call_anthropic()
        else:
            raise UserError(
                "No AI provider configured. Please select OpenAI or Anthropic "
                "in Settings > Assetz > AI Recommendations."
            )

    def _get_ai_prompt(self):
        """Build the prompt for AI checklist recommendations."""
        # Build context from categories
        category_info = ""
        if self.category_ids:
            category_names = ", ".join(self.category_ids.mapped("name"))
            category_info = f"Asset Categories: {category_names}\n"

        # Build context from asset
        asset_info = ""
        if self.asset_id:
            asset = self.asset_id
            asset_details = [f"Asset Name: {asset.name}"]
            if asset.serial_number:
                asset_details.append(f"Serial Number: {asset.serial_number}")
            if asset.model:
                asset_details.append(f"Model: {asset.model}")
            if asset.manufacturer:
                asset_details.append(f"Manufacturer: {asset.manufacturer}")
            if asset.category_id:
                asset_details.append(f"Asset Category: {asset.category_id.name}")
            if asset.description:
                asset_details.append(f"Description: {asset.description}")
            asset_info = "\n".join(asset_details) + "\n"

        # Maintenance type descriptions
        type_descriptions = {
            "preventive": "routine preventive maintenance to prevent breakdowns",
            "corrective": "corrective maintenance to fix identified issues",
            "inspection": "thorough inspection and assessment",
            "calibration": "calibration and precision adjustment",
            "general": "general maintenance and upkeep",
        }
        maint_desc = type_descriptions.get(self.maintenance_type, "maintenance")

        # Build the prompt
        prompt = f"""You are an expert maintenance engineer. Generate a comprehensive
maintenance checklist for {maint_desc}.

{category_info}{asset_info}
Asset/Equipment Description: {self.asset_description or 'General equipment'}

Additional Context: {self.additional_context or 'None specified'}

Generate 10-20 checklist items that a technician should verify during this maintenance.
Group items by logical sections (e.g., Safety, Visual Inspection, Functional Tests, etc.).

Respond ONLY with valid JSON in this exact format:

{{
    "checklist_items": [
        {{
            "group": "Section/Group name (e.g., Safety Checks, Visual Inspection)",
            "name": "Short descriptive name of the check item",
            "description": "Detailed instructions for the technician",
            "check_type": "boolean|reading|text|selection",
            "is_required": true or false,
            "requires_photo": true or false,
            "expected_min": null or number (for reading type),
            "expected_max": null or number (for reading type),
            "unit": null or string (for reading type, e.g., "PSI", "°C"),
            "selection_options": null or "Option1,Option2,Option3" (for selection type)
        }}
    ]
}}

Guidelines for check_type:
- "boolean": Use for Pass/Fail checks (most common)
- "reading": Use when a measurement value is needed (temperature, pressure, etc.)
- "text": Use when detailed notes are needed
- "selection": Use when choosing from predefined options (Good/Fair/Poor, Yes/No/NA)

Make items specific, actionable, and relevant to the equipment type.
Include safety checks at the beginning of the list.
For "reading" type, always provide expected_min, expected_max, and unit.
For "selection" type, always provide selection_options."""

        return prompt

    def _call_openai(self):
        """Call OpenAI API for recommendations."""
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

        prompt = self._get_ai_prompt()

        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert maintenance engineer who creates "
                        "comprehensive maintenance checklists. Always respond with "
                        "valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=4000,
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

    def _call_anthropic(self):
        """Call Anthropic Claude API for recommendations."""
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

        prompt = self._get_ai_prompt()

        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=4000,
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

    def _create_preview_line(self, item_data, sequence):
        """Create a preview line from AI response."""
        # Map check type
        check_type = item_data.get("check_type", "boolean")
        if check_type not in ("boolean", "reading", "text", "selection", "photo"):
            check_type = "boolean"

        vals = {
            "wizard_id": self.id,
            "sequence": sequence * 10,
            "include": True,
            "group_name": item_data.get("group", ""),
            "name": item_data.get("name", ""),
            "description": item_data.get("description", ""),
            "check_type": check_type,
            "is_required": item_data.get("is_required", True),
            "requires_photo": item_data.get("requires_photo", False),
        }

        # Handle reading type fields
        if check_type == "reading":
            vals["expected_min"] = item_data.get("expected_min") or 0
            vals["expected_max"] = item_data.get("expected_max") or 0
            vals["unit"] = item_data.get("unit") or ""

        # Handle selection type
        if check_type == "selection":
            vals["selection_options"] = item_data.get("selection_options") or ""

        return self.env["assetz.ai.checklist.wizard.line"].create(vals)

    def action_apply_recommendations(self):
        """Add selected recommendations to the template or maintenance order."""
        self.ensure_one()

        selected_lines = self.preview_line_ids.filtered("include")
        if not selected_lines:
            raise UserError("Please select at least one item to add.")

        # Determine target: order or template
        if self.order_id:
            return self._apply_to_order(selected_lines)
        elif self.template_id:
            return self._apply_to_template(selected_lines)
        else:
            raise UserError("No template or order selected. Cannot add items.")

    def _apply_to_template(self, selected_lines):
        """Add selected lines to a checklist template."""
        # Get current max sequence in template
        existing_lines = self.template_id.line_ids
        max_seq = max(existing_lines.mapped("sequence")) if existing_lines else 0

        # Create template lines
        for line in selected_lines:
            max_seq += 10
            self.env["assetz.checklist.template.line"].create(
                {
                    "template_id": self.template_id.id,
                    "sequence": max_seq,
                    "group_name": line.group_name,
                    "name": line.name,
                    "description": line.description,
                    "check_type": line.check_type,
                    "is_required": line.is_required,
                    "requires_photo": line.requires_photo,
                    "expected_min": line.expected_min,
                    "expected_max": line.expected_max,
                    "unit": line.unit,
                    "selection_options": line.selection_options,
                }
            )

        # Return to template form
        return {
            "type": "ir.actions.act_window",
            "res_model": "assetz.checklist.template",
            "res_id": self.template_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def _apply_to_order(self, selected_lines):
        """Add selected lines directly to a maintenance order's checklist."""
        # Get current max sequence in order's checklist
        existing_lines = self.order_id.checklist_line_ids
        max_seq = max(existing_lines.mapped("sequence")) if existing_lines else 0

        # Create checklist lines on the maintenance order
        for line in selected_lines:
            max_seq += 10
            self.env["assetz.maintenance.checklist.line"].create(
                {
                    "order_id": self.order_id.id,
                    "sequence": max_seq,
                    "group_name": line.group_name,
                    "name": line.name,
                    "description": line.description,
                    "check_type": line.check_type,
                    "is_required": line.is_required,
                    "requires_photo": line.requires_photo,
                    "expected_min": line.expected_min,
                    "expected_max": line.expected_max,
                    "unit": line.unit,
                    "selection_options": line.selection_options,
                }
            )

        # Return to maintenance order form
        return {
            "type": "ir.actions.act_window",
            "res_model": "assetz.maintenance.order",
            "res_id": self.order_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_back(self):
        """Go back to input state."""
        self.ensure_one()
        self.state = "input"
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class AIChecklistWizardLine(models.TransientModel):
    """Preview line for AI checklist recommendations."""

    _name = "assetz.ai.checklist.wizard.line"
    _description = "AI Checklist Wizard Line"
    _order = "sequence, id"

    wizard_id = fields.Many2one(
        comodel_name="assetz.ai.checklist.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    include = fields.Boolean(string="Include", default=True)

    # === Check Item Fields ===
    group_name = fields.Char(string="Section/Group")
    name = fields.Char(string="Check Item", required=True)
    description = fields.Text(string="Instructions")
    check_type = fields.Selection(
        selection=[
            ("boolean", "Pass/Fail"),
            ("reading", "Numeric Reading"),
            ("text", "Text Entry"),
            ("selection", "Selection/Choice"),
            ("photo", "Photo Only"),
        ],
        string="Type",
        default="boolean",
    )
    is_required = fields.Boolean(string="Required", default=True)
    requires_photo = fields.Boolean(string="Photo Required")

    # === Reading Type Fields ===
    expected_min = fields.Float(string="Min Value")
    expected_max = fields.Float(string="Max Value")
    unit = fields.Char(string="Unit")

    # === Selection Type Fields ===
    selection_options = fields.Char(string="Options")
