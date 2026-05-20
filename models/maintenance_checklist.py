from odoo import api, fields, models


class AssetzChecklistTemplate(models.Model):
    """Reusable checklist templates for maintenance tasks."""

    _name = "assetz.checklist.template"
    _description = "Checklist Template"
    _inherit = ["mail.thread"]
    _order = "name"

    # === Basic Information ===
    name = fields.Char(
        string="Template Name",
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
    description = fields.Text(string="Description")

    # === Scope ===
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
        help="Type of maintenance this template is designed for",
    )

    # Category-specific templates
    category_ids = fields.Many2many(
        comodel_name="assetz.category",
        relation="checklist_template_category_rel",
        column1="template_id",
        column2="category_id",
        string="Applicable Categories",
        help="Leave empty to apply to all asset categories",
    )

    # Asset-specific templates
    asset_ids = fields.Many2many(
        comodel_name="assetz.asset",
        relation="checklist_template_asset_rel",
        column1="template_id",
        column2="asset_id",
        string="Applicable Assets",
        help="Specific assets this template applies to (optional)",
    )

    # === Template Lines ===
    line_ids = fields.One2many(
        comodel_name="assetz.checklist.template.line",
        inverse_name="template_id",
        string="Checklist Items",
        copy=True,
    )
    line_count = fields.Integer(
        string="Item Count",
        compute="_compute_line_count",
    )

    # === Estimated Duration ===
    estimated_duration = fields.Float(
        string="Est. Duration (Hours)",
        help="Estimated time to complete this checklist",
    )

    # === Instructions ===
    instructions = fields.Html(
        string="General Instructions",
        help="Instructions displayed at the top of the checklist",
    )
    safety_notes = fields.Text(
        string="Safety Notes",
        help="Safety warnings and precautions",
    )

    # === Usage Statistics ===
    usage_count = fields.Integer(
        string="Times Used",
        compute="_compute_usage_count",
        help="Number of maintenance orders using this template",
    )

    # === Company ===
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # === Computed Methods ===

    @api.depends("line_ids")
    def _compute_line_count(self):
        """Count template lines."""
        for template in self:
            template.line_count = len(template.line_ids)

    def _compute_usage_count(self):
        """Count how many orders use this template."""
        for template in self:
            template.usage_count = self.env["assetz.maintenance.order"].search_count(
                [("checklist_template_id", "=", template.id)]
            )

    # === CRUD Methods ===

    @api.model_create_multi
    def create(self, vals_list):
        """Generate template code on creation."""
        for vals in vals_list:
            if vals.get("code", "New") == "New":
                vals["code"] = (
                    self.env["ir.sequence"].next_by_code("assetz.checklist.template")
                    or "New"
                )
        return super().create(vals_list)

    # === Action Methods ===

    def action_duplicate(self):
        """Duplicate the template."""
        self.ensure_one()
        new_template = self.copy({"name": f"{self.name} (Copy)"})
        return {
            "type": "ir.actions.act_window",
            "res_model": "assetz.checklist.template",
            "res_id": new_template.id,
            "view_mode": "form",
        }

    def action_view_orders(self):
        """View maintenance orders using this template."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Maintenance Orders",
            "res_model": "assetz.maintenance.order",
            "view_mode": "list,form",
            "domain": [("checklist_template_id", "=", self.id)],
        }

    def action_ai_recommendations(self):
        """Open AI checklist recommendations wizard."""
        self.ensure_one()
        context = {
            "default_template_id": self.id,
            "default_maintenance_type": self.maintenance_type,
            "default_category_ids": [(6, 0, self.category_ids.ids)],
        }
        # If there's exactly one asset, pre-select it in the wizard
        if len(self.asset_ids) == 1:
            context["default_asset_id"] = self.asset_ids.id
        return {
            "type": "ir.actions.act_window",
            "name": "AI Checklist Recommendations",
            "res_model": "assetz.ai.checklist.wizard",
            "view_mode": "form",
            "target": "new",
            "context": context,
        }


class AssetzChecklistTemplateLine(models.Model):
    """Individual items in a checklist template."""

    _name = "assetz.checklist.template.line"
    _description = "Checklist Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one(
        comodel_name="assetz.checklist.template",
        string="Template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)

    # === Item Details ===
    name = fields.Char(
        string="Check Item",
        required=True,
    )
    description = fields.Text(
        string="Detailed Instructions",
        help="Step-by-step instructions for this check item",
    )

    # === Item Type ===
    check_type = fields.Selection(
        selection=[
            ("boolean", "Pass/Fail"),
            ("reading", "Numeric Reading"),
            ("text", "Text Entry"),
            ("selection", "Selection/Choice"),
            ("photo", "Photo Only"),
        ],
        string="Check Type",
        required=True,
        default="boolean",
        help="Type of input expected for this item",
    )

    # === For Reading Type - Expected Values ===
    expected_min = fields.Float(
        string="Min Value",
        help="Minimum acceptable value for readings",
    )
    expected_max = fields.Float(
        string="Max Value",
        help="Maximum acceptable value for readings",
    )
    unit = fields.Char(
        string="Unit",
        help="Unit of measurement (e.g., PSI, °C, mm)",
    )

    # === For Selection Type ===
    selection_options = fields.Char(
        string="Options",
        help="Comma-separated options (e.g., 'Good,Fair,Poor')",
    )

    # === Requirements ===
    is_required = fields.Boolean(
        string="Required",
        default=True,
        help="If checked, this item must be completed before order can be closed",
    )
    requires_photo = fields.Boolean(
        string="Photo Required",
        help="A photo must be attached for this item",
    )
    requires_notes = fields.Boolean(
        string="Notes Required",
        help="Notes must be entered for this item",
    )

    # === Grouping ===
    group_name = fields.Char(
        string="Section/Group",
        help="Group items by section (e.g., 'Safety Checks', 'Lubrication')",
    )

    # === Display Helper ===
    display_name = fields.Char(
        compute="_compute_display_name",
    )

    @api.depends("name", "check_type")
    def _compute_display_name(self):
        """Compute display name."""
        type_labels = {
            "boolean": "Pass/Fail",
            "reading": "Reading",
            "text": "Text",
            "selection": "Selection",
            "photo": "Photo",
        }
        for line in self:
            type_label = type_labels.get(line.check_type, "")
            line.display_name = f"{line.name} [{type_label}]"

    @api.onchange("check_type")
    def _onchange_check_type(self):
        """Reset type-specific fields when type changes."""
        if self.check_type != "reading":
            self.expected_min = 0
            self.expected_max = 0
            self.unit = False
        if self.check_type != "selection":
            self.selection_options = False
        if self.check_type == "photo":
            self.requires_photo = True
