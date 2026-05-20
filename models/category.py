from odoo import api, fields, models

from .industry_examples import INDUSTRY_EXAMPLES


class AssetzCategory(models.Model):
    """Custom category model with configurable attributes for assets."""

    _name = "assetz.category"
    _description = "Asset Category"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "sequence, name"

    # Industry-specific example text (computed from settings)
    example_category_name = fields.Char(
        string="Example Category Name",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )
    example_code_prefix = fields.Char(
        string="Example Code Prefix",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )
    example_attribute_name = fields.Char(
        string="Example Attribute Name",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )
    example_attribute_options = fields.Char(
        string="Example Attribute Options",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )

    def _compute_industry_examples(self):
        """Compute industry-specific example text based on settings."""
        industry = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.industry_preset", "custom"
        )
        examples = INDUSTRY_EXAMPLES.get(industry, INDUSTRY_EXAMPLES["custom"])
        for rec in self:
            rec.example_category_name = f"e.g. {examples.get('category_name', '')}"
            rec.example_code_prefix = f"e.g. {examples.get('code_prefix', '')}"
            rec.example_attribute_name = f"e.g. {examples.get('attribute_name', '')}"
            rec.example_attribute_options = f"e.g. {examples.get('attribute_options', '')}"

    name = fields.Char(string="Category Name", required=True, translate=True)
    code = fields.Char(string="Code", help="Short code for the category")
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(string="Sequence", default=10)
    color = fields.Integer(string="Color")

    # Hierarchy
    parent_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Parent Category",
        index=True,
        ondelete="cascade",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        comodel_name="assetz.category",
        inverse_name="parent_id",
        string="Child Categories",
    )

    # Asset code prefix for auto-generation
    code_prefix = fields.Char(
        string="Asset Code Prefix",
        help="Prefix used when auto-generating asset codes for this category (e.g., LAP for laptops)",
    )

    # Default values for assets in this category
    default_useful_life = fields.Integer(
        string="Default Useful Life (Years)",
        help="Default useful life in years for assets in this category",
    )
    depreciation_method = fields.Selection(
        selection=[
            ("none", "No Depreciation"),
            ("straight", "Straight Line"),
            ("declining", "Declining Balance"),
        ],
        string="Depreciation Method",
        default="none",
    )

    # Feature toggles per category (override global settings)
    require_serial_number = fields.Boolean(
        string="Require Serial Number",
        help="If checked, serial number is mandatory for assets in this category",
    )
    require_location = fields.Boolean(
        string="Require Location",
        help="If checked, location is mandatory for assets in this category",
    )
    require_approval = fields.Boolean(
        string="Require Approval",
        help="If checked, assets in this category require approval before activation",
    )
    require_request = fields.Boolean(
        string="Require Asset Request",
        help="If checked, assets in this category cannot be issued without an approved asset request",
    )
    approver_ids = fields.Many2many(
        comodel_name="res.users",
        relation="assetz_category_approver_rel",
        column1="category_id",
        column2="user_id",
        string="Approvers",
        help="Users who can approve assets in this category",
    )

    # Dynamic attributes
    attribute_ids = fields.One2many(
        comodel_name="assetz.category.attribute",
        inverse_name="category_id",
        string="Attributes",
        help="Custom attributes for assets in this category",
    )

    # Statistics
    asset_count = fields.Integer(
        string="Asset Count",
        compute="_compute_asset_count",
    )

    # Stock/On-Hand Tracking
    total_assets = fields.Integer(
        string="Total Assets",
        compute="_compute_stock_counts",
        help="Total number of non-retired assets in this category",
    )
    available_count = fields.Integer(
        string="Available",
        compute="_compute_stock_counts",
        help="Number of assets available for issuance",
    )
    issued_count = fields.Integer(
        string="Issued",
        compute="_compute_stock_counts",
        help="Number of assets currently issued",
    )
    reserved_count = fields.Integer(
        string="Reserved",
        compute="_compute_stock_counts",
        help="Number of assets currently reserved",
    )
    maintenance_count = fields.Integer(
        string="In Maintenance",
        compute="_compute_stock_counts",
        help="Number of assets under maintenance",
    )

    _sql_constraints = [
        (
            "code_uniq",
            "unique(code)",
            "Category code must be unique!",
        ),
    ]

    @api.depends("child_ids")
    def _compute_asset_count(self):
        """Compute the number of assets in this category."""
        asset_model = self.env["assetz.asset"]
        for category in self:
            category.asset_count = asset_model.search_count(
                [("category_id", "=", category.id)]
            )

    def _compute_stock_counts(self):
        """Compute asset counts by status for each category."""
        asset_model = self.env["assetz.asset"]
        for category in self:
            # Get all non-retired assets in this category
            all_assets = asset_model.search([
                ("category_id", "=", category.id),
                ("state", "!=", "retired"),
            ])
            category.total_assets = len(all_assets)

            # Count by issue state
            category.available_count = len(all_assets.filtered(
                lambda a: a.issue_state == "available" and a.state == "active"
            ))
            category.issued_count = len(all_assets.filtered(
                lambda a: a.issue_state == "issued"
            ))
            category.reserved_count = len(all_assets.filtered(
                lambda a: a.issue_state == "reserved"
            ))
            category.maintenance_count = len(all_assets.filtered(
                lambda a: a.state == "maintenance"
            ))

    def action_view_assets(self):
        """Open assets view filtered by this category."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Assets - {self.name}",
            "res_model": "assetz.asset",
            "view_mode": "list,kanban,form",
            "views": [(False, "list"), (False, "kanban"), (False, "form")],
            "domain": [("category_id", "=", self.id), ("state", "!=", "retired")],
            "context": {"default_category_id": self.id},
        }

    def action_view_available_assets(self):
        """Open assets view filtered by available assets in this category."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Available Assets - {self.name}",
            "res_model": "assetz.asset",
            "view_mode": "list,kanban,form",
            "views": [(False, "list"), (False, "kanban"), (False, "form")],
            "domain": [
                ("category_id", "=", self.id),
                ("issue_state", "=", "available"),
                ("state", "=", "active"),
            ],
            "context": {"default_category_id": self.id},
        }

    def action_view_issued_assets(self):
        """Open assets view filtered by issued assets in this category."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Issued Assets - {self.name}",
            "res_model": "assetz.asset",
            "view_mode": "list,kanban,form",
            "views": [(False, "list"), (False, "kanban"), (False, "form")],
            "domain": [
                ("category_id", "=", self.id),
                ("issue_state", "=", "issued"),
            ],
            "context": {"default_category_id": self.id},
        }

    def name_get(self):
        """Return full path name for categories."""
        result = []
        for category in self:
            names = []
            current = category
            while current:
                names.append(current.name)
                current = current.parent_id
            result.append((category.id, " / ".join(reversed(names))))
        return result

    @api.constrains("parent_id")
    def _check_parent_id(self):
        """Prevent circular references in category hierarchy."""
        if not self._check_recursion():
            raise models.ValidationError(
                "Error! You cannot create recursive categories."
            )


class AssetzCategoryAttributeOption(models.Model):
    """Option values for dropdown/selection type attributes."""

    _name = "assetz.category.attribute.option"
    _description = "Attribute Option"
    _order = "sequence, id"

    # Industry-specific example text (computed from settings)
    example_attribute_options = fields.Char(
        string="Example Options",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )

    def _compute_industry_examples(self):
        """Compute industry-specific example text based on settings."""
        industry = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.industry_preset", "custom"
        )
        examples = INDUSTRY_EXAMPLES.get(industry, INDUSTRY_EXAMPLES["custom"])
        for rec in self:
            rec.example_attribute_options = f"e.g. {examples.get('attribute_options', '')}"

    name = fields.Char(string="Option Value", required=True)
    attribute_id = fields.Many2one(
        comodel_name="assetz.category.attribute",
        string="Attribute",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    is_default = fields.Boolean(
        string="Default",
        help="If checked, this option will be pre-selected for new assets",
    )

    _sql_constraints = [
        (
            "name_attribute_uniq",
            "unique(name, attribute_id)",
            "Option value must be unique per attribute!",
        ),
    ]


class AssetzCategoryAttribute(models.Model):
    """Attribute definitions for asset categories."""

    _name = "assetz.category.attribute"
    _description = "Category Attribute"
    _order = "sequence, id"

    # Industry-specific example text (computed from settings)
    example_attribute_name = fields.Char(
        string="Example Attribute Name",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )
    example_attribute_options = fields.Char(
        string="Example Attribute Options",
        compute="_compute_industry_examples",
        compute_sudo=True,
    )

    def _compute_industry_examples(self):
        """Compute industry-specific example text based on settings."""
        industry = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.industry_preset", "custom"
        )
        examples = INDUSTRY_EXAMPLES.get(industry, INDUSTRY_EXAMPLES["custom"])
        for rec in self:
            rec.example_attribute_name = f"e.g. {examples.get('attribute_name', '')}"
            rec.example_attribute_options = f"e.g. {examples.get('attribute_options', '')}"

    name = fields.Char(string="Attribute Name", required=True)
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Category",
        required=True,
        ondelete="cascade",
    )

    attribute_type = fields.Selection(
        selection=[
            ("char", "Text"),
            ("integer", "Whole Number"),
            ("float", "Decimal Number"),
            ("date", "Date"),
            ("selection", "Dropdown"),
            ("boolean", "Yes/No"),
        ],
        string="Type",
        required=True,
        default="char",
    )

    # Dropdown options - One2many to option records
    option_ids = fields.One2many(
        comodel_name="assetz.category.attribute.option",
        inverse_name="attribute_id",
        string="Options",
        help="Available options for dropdown attributes",
    )

    # Display helper for options count
    options_count = fields.Integer(
        string="Options",
        compute="_compute_options_count",
    )

    # Validation and display
    is_required = fields.Boolean(string="Required")
    default_value = fields.Char(
        string="Default Value",
        help="Default value for this attribute (for non-dropdown types)",
    )
    help_text = fields.Char(
        string="Help Text",
        help="Tooltip text to help users understand this attribute",
    )
    sequence = fields.Integer(string="Display Order", default=10)

    @api.depends("option_ids")
    def _compute_options_count(self):
        """Compute number of dropdown options."""
        for attr in self:
            attr.options_count = len(attr.option_ids)

    def get_default_option(self):
        """Get the default option for this attribute."""
        self.ensure_one()
        if self.attribute_type == "selection" and self.option_ids:
            default_opt = self.option_ids.filtered(lambda o: o.is_default)
            if default_opt:
                return default_opt[0]
            # Return first option if no default set
            return self.option_ids[0] if self.option_ids else False
        return False


class AssetzAssetAttributeValue(models.Model):
    """Store dynamic attribute values for assets."""

    _name = "assetz.asset.attribute.value"
    _description = "Asset Attribute Value"
    _order = "sequence, id"

    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
        ondelete="cascade",
    )
    attribute_id = fields.Many2one(
        comodel_name="assetz.category.attribute",
        string="Attribute",
        required=True,
        ondelete="cascade",
    )

    # Sequence from attribute for ordering
    sequence = fields.Integer(
        related="attribute_id.sequence",
        store=True,
    )

    # Related fields for display
    attribute_name = fields.Char(
        related="attribute_id.name",
        string="Attribute",
        store=True,
    )
    attribute_type = fields.Selection(
        related="attribute_id.attribute_type",
        string="Type",
        store=True,
    )
    is_required = fields.Boolean(
        related="attribute_id.is_required",
        string="Required",
    )
    help_text = fields.Char(
        related="attribute_id.help_text",
        string="Help",
    )

    # Single unified value field - stores everything as text
    value = fields.Char(
        string="Value",
        help="The value for this specification",
    )

    # For dropdown/selection type - stores the selected option
    value_selection_id = fields.Many2one(
        comodel_name="assetz.category.attribute.option",
        string="Selected Option",
        domain="[('attribute_id', '=', attribute_id)]",
        ondelete="set null",
    )

    # Display value - what the user sees
    display_value = fields.Char(
        string="Display Value",
        compute="_compute_display_value",
        store=True,
    )

    _sql_constraints = [
        (
            "asset_attribute_uniq",
            "unique(asset_id, attribute_id)",
            "Each attribute can only have one value per asset!",
        ),
    ]

    @api.depends("value", "value_selection_id", "value_selection_id.name", "attribute_type")
    def _compute_display_value(self):
        """Compute human-readable display value."""
        for rec in self:
            if rec.attribute_type == "selection":
                rec.display_value = rec.value_selection_id.name if rec.value_selection_id else ""
            elif rec.attribute_type == "boolean":
                rec.display_value = "Yes" if rec.value and rec.value.lower() in ("true", "yes", "1") else "No"
            else:
                rec.display_value = rec.value or ""

    @api.onchange("value_selection_id")
    def _onchange_value_selection_id(self):
        """Sync selection to value field."""
        if self.value_selection_id:
            self.value = self.value_selection_id.name
