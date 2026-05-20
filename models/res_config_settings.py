from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Configuration settings for Assetz module."""

    _inherit = "res.config.settings"

    # Industry Preset
    assetz_industry_preset = fields.Selection(
        selection=[
            ("it", "IT / Technology"),
            ("manufacturing", "Manufacturing"),
            ("healthcare", "Healthcare"),
            ("realestate", "Real Estate / Facilities"),
            ("fleet", "Fleet / Vehicles"),
            ("custom", "Custom Configuration"),
        ],
        string="Industry Preset",
        default="custom",
        help="Select an industry preset to auto-configure recommended settings",
    )

    # Feature Toggles
    assetz_enable_qr_codes = fields.Boolean(
        string="Enable QR Code Generation",
        default=True,
    )
    assetz_enable_serial_auto_generation = fields.Boolean(
        string="Auto-generate Serial Numbers",
        default=True,
    )
    assetz_enable_location_tracking = fields.Boolean(
        string="Enable Location Tracking",
        default=True,
    )
    assetz_enable_location_hierarchy = fields.Boolean(
        string="Enable Location Hierarchy",
        default=False,
        help="Enable multi-level locations (Warehouse > Zone > Bin)",
    )
    assetz_enable_movement_logging = fields.Boolean(
        string="Log All Asset Movements",
        default=False,
    )
    assetz_enable_barcode_scanning = fields.Boolean(
        string="Enable Barcode/QR Scanning",
        default=False,
    )
    assetz_enable_asset_issuance = fields.Boolean(
        string="Enable Asset Issue/Return Workflow",
        default=True,
    )
    assetz_enable_asset_requests = fields.Boolean(
        string="Enable Employee Asset Requests",
        default=False,
    )
    assetz_enable_category_approval = fields.Boolean(
        string="Enable Category-level Approval",
        default=False,
    )
    assetz_enable_eol_tracking = fields.Boolean(
        string="Enable End of Life Tracking",
        default=True,
    )
    assetz_enable_eol_notifications = fields.Boolean(
        string="Enable EOL Reminder Notifications",
        default=True,
    )
    assetz_enable_ai_recommendations = fields.Boolean(
        string="Enable AI-based Recommendations",
        default=False,
    )
    assetz_enable_erp_import = fields.Boolean(
        string="Enable External ERP Import",
        default=False,
    )

    # Purchase Integration
    assetz_enable_purchase_requests = fields.Boolean(
        string="Enable Purchase Requests",
        default=True,
        help="Enable purchase request workflow for ordering new assets",
    )
    assetz_auto_create_assets_from_po = fields.Boolean(
        string="Auto-create Assets from Purchase Orders",
        default=False,
        help="If enabled, assets are created automatically when PO is received. "
        "If disabled, a wizard prompts for manual asset creation.",
    )
    assetz_default_asset_purchase_product_id = fields.Many2one(
        comodel_name="product.product",
        string="Default Purchase Product",
        help="Product used when creating purchase order lines for asset purchases",
    )

    # Warranty/Service Contract Settings
    assetz_enable_warranty_tracking = fields.Boolean(
        string="Enable Warranty/Contract Tracking",
        default=True,
        help="Track warranty and service contracts for assets",
    )
    assetz_enable_maintenance_integration = fields.Boolean(
        string="Enable Maintenance Integration",
        default=True,
        help="Integrate with Odoo Maintenance module for work orders",
    )
    assetz_contract_expiry_reminder_days = fields.Integer(
        string="Contract Expiry Reminder Days",
        default=30,
        help="Days before contract expiry to send reminder",
    )
    assetz_default_labor_rate = fields.Float(
        string="Default Labor Rate",
        default=50.0,
        help="Default hourly labor rate for maintenance work",
    )
    assetz_auto_determine_billing = fields.Boolean(
        string="Auto-determine Billing on WO Close",
        default=True,
        help="Automatically calculate billing when closing work orders",
    )

    # Configurable Parameters
    assetz_serial_number_prefix = fields.Char(
        string="Serial Number Prefix",
        default="AST",
    )
    assetz_serial_number_padding = fields.Integer(
        string="Serial Number Digits",
        default=5,
    )
    assetz_qr_code_size = fields.Integer(
        string="QR Code Size (pixels)",
        default=200,
    )
    assetz_eol_reminder_days = fields.Integer(
        string="EOL Reminder Days Before",
        default=7,
    )
    assetz_default_useful_life = fields.Integer(
        string="Default Useful Life (Years)",
        default=5,
    )

    # AI Configuration
    assetz_ai_provider = fields.Selection(
        selection=[
            ("openai", "OpenAI (GPT-4)"),
            ("anthropic", "Anthropic (Claude)"),
            ("none", "Rule-based (No AI)"),
        ],
        string="AI Provider",
        default="none",
    )
    assetz_openai_api_key = fields.Char(
        string="OpenAI API Key",
    )
    assetz_anthropic_api_key = fields.Char(
        string="Anthropic API Key",
    )
    assetz_ai_attribute_level = fields.Selection(
        selection=[
            ("1", "Level 1 - Critical (Max 5 attributes)"),
            ("2", "Level 2 - Standard (Max 10 attributes)"),
            ("3", "Level 3 - Comprehensive (Max 20 attributes)"),
        ],
        string="AI Attribute Level",
        default="2",
        help="Controls how many attributes AI recommends when creating new categories",
    )

    def set_values(self):
        """Save Assetz settings to ir.config_parameter."""
        super().set_values()
        ICP = self.env["ir.config_parameter"].sudo()
        # Boolean fields - store as 'True' or 'False' strings
        ICP.set_param("assetz.enable_qr_codes", str(self.assetz_enable_qr_codes))
        ICP.set_param(
            "assetz.enable_serial_auto_generation",
            str(self.assetz_enable_serial_auto_generation),
        )
        ICP.set_param(
            "assetz.enable_location_tracking", str(self.assetz_enable_location_tracking)
        )
        ICP.set_param(
            "assetz.enable_location_hierarchy",
            str(self.assetz_enable_location_hierarchy),
        )
        ICP.set_param(
            "assetz.enable_movement_logging", str(self.assetz_enable_movement_logging)
        )
        ICP.set_param(
            "assetz.enable_barcode_scanning", str(self.assetz_enable_barcode_scanning)
        )
        ICP.set_param(
            "assetz.enable_asset_issuance", str(self.assetz_enable_asset_issuance)
        )
        ICP.set_param(
            "assetz.enable_asset_requests", str(self.assetz_enable_asset_requests)
        )
        ICP.set_param(
            "assetz.enable_category_approval", str(self.assetz_enable_category_approval)
        )
        ICP.set_param(
            "assetz.enable_eol_tracking", str(self.assetz_enable_eol_tracking)
        )
        ICP.set_param(
            "assetz.enable_eol_notifications", str(self.assetz_enable_eol_notifications)
        )
        ICP.set_param(
            "assetz.enable_ai_recommendations",
            str(self.assetz_enable_ai_recommendations),
        )
        ICP.set_param("assetz.enable_erp_import", str(self.assetz_enable_erp_import))
        # Purchase Integration
        ICP.set_param(
            "assetz.enable_purchase_requests", str(self.assetz_enable_purchase_requests)
        )
        ICP.set_param(
            "assetz.auto_create_assets_from_po",
            str(self.assetz_auto_create_assets_from_po),
        )
        ICP.set_param(
            "assetz.default_asset_purchase_product_id",
            str(self.assetz_default_asset_purchase_product_id.id)
            if self.assetz_default_asset_purchase_product_id
            else "",
        )
        # Warranty/Service Contract Settings
        ICP.set_param(
            "assetz.enable_warranty_tracking", str(self.assetz_enable_warranty_tracking)
        )
        ICP.set_param(
            "assetz.enable_maintenance_integration",
            str(self.assetz_enable_maintenance_integration),
        )
        ICP.set_param(
            "assetz.contract_expiry_reminder_days",
            str(self.assetz_contract_expiry_reminder_days or 30),
        )
        ICP.set_param(
            "assetz.default_labor_rate", str(self.assetz_default_labor_rate or 50.0)
        )
        ICP.set_param(
            "assetz.auto_determine_billing", str(self.assetz_auto_determine_billing)
        )
        # Other fields
        ICP.set_param("assetz.industry_preset", self.assetz_industry_preset or "custom")
        ICP.set_param(
            "assetz.serial_number_prefix", self.assetz_serial_number_prefix or "AST"
        )
        ICP.set_param(
            "assetz.serial_number_padding", str(self.assetz_serial_number_padding or 5)
        )
        ICP.set_param("assetz.qr_code_size", str(self.assetz_qr_code_size or 200))
        ICP.set_param(
            "assetz.eol_reminder_days", str(self.assetz_eol_reminder_days or 7)
        )
        ICP.set_param(
            "assetz.default_useful_life", str(self.assetz_default_useful_life or 5)
        )
        ICP.set_param("assetz.ai_provider", self.assetz_ai_provider or "none")
        ICP.set_param("assetz.openai_api_key", self.assetz_openai_api_key or "")
        ICP.set_param("assetz.anthropic_api_key", self.assetz_anthropic_api_key or "")
        ICP.set_param("assetz.ai_attribute_level", self.assetz_ai_attribute_level or "2")

    @api.model
    def get_values(self):
        """Load Assetz settings from ir.config_parameter."""
        res = super().get_values()
        ICP = self.env["ir.config_parameter"].sudo()

        # Helper to convert string to boolean
        def str_to_bool(value, default=False):
            if value is None or value == "" or value is False:
                return default
            return value == "True"

        # Helper to safely convert to int
        def safe_int(value, default=0):
            try:
                return int(value) if value else default
            except (ValueError, TypeError):
                return default

        res.update(
            assetz_enable_qr_codes=str_to_bool(
                ICP.get_param("assetz.enable_qr_codes"), True
            ),
            assetz_enable_serial_auto_generation=str_to_bool(
                ICP.get_param("assetz.enable_serial_auto_generation"), True
            ),
            assetz_enable_location_tracking=str_to_bool(
                ICP.get_param("assetz.enable_location_tracking"), True
            ),
            assetz_enable_location_hierarchy=str_to_bool(
                ICP.get_param("assetz.enable_location_hierarchy"), False
            ),
            assetz_enable_movement_logging=str_to_bool(
                ICP.get_param("assetz.enable_movement_logging"), False
            ),
            assetz_enable_barcode_scanning=str_to_bool(
                ICP.get_param("assetz.enable_barcode_scanning"), False
            ),
            assetz_enable_asset_issuance=str_to_bool(
                ICP.get_param("assetz.enable_asset_issuance"), True
            ),
            assetz_enable_asset_requests=str_to_bool(
                ICP.get_param("assetz.enable_asset_requests"), False
            ),
            assetz_enable_category_approval=str_to_bool(
                ICP.get_param("assetz.enable_category_approval"), False
            ),
            assetz_enable_eol_tracking=str_to_bool(
                ICP.get_param("assetz.enable_eol_tracking"), True
            ),
            assetz_enable_eol_notifications=str_to_bool(
                ICP.get_param("assetz.enable_eol_notifications"), True
            ),
            assetz_enable_ai_recommendations=str_to_bool(
                ICP.get_param("assetz.enable_ai_recommendations"), False
            ),
            assetz_enable_erp_import=str_to_bool(
                ICP.get_param("assetz.enable_erp_import"), False
            ),
            # Purchase Integration
            assetz_enable_purchase_requests=str_to_bool(
                ICP.get_param("assetz.enable_purchase_requests"), True
            ),
            assetz_auto_create_assets_from_po=str_to_bool(
                ICP.get_param("assetz.auto_create_assets_from_po"), False
            ),
            assetz_default_asset_purchase_product_id=safe_int(
                ICP.get_param("assetz.default_asset_purchase_product_id"), False
            ),
            # Warranty/Service Contract Settings
            assetz_enable_warranty_tracking=str_to_bool(
                ICP.get_param("assetz.enable_warranty_tracking"), True
            ),
            assetz_enable_maintenance_integration=str_to_bool(
                ICP.get_param("assetz.enable_maintenance_integration"), True
            ),
            assetz_contract_expiry_reminder_days=safe_int(
                ICP.get_param("assetz.contract_expiry_reminder_days"), 30
            ),
            assetz_default_labor_rate=float(
                ICP.get_param("assetz.default_labor_rate") or 50.0
            ),
            assetz_auto_determine_billing=str_to_bool(
                ICP.get_param("assetz.auto_determine_billing"), True
            ),
            assetz_industry_preset=ICP.get_param("assetz.industry_preset") or "custom",
            assetz_serial_number_prefix=ICP.get_param("assetz.serial_number_prefix")
            or "AST",
            assetz_serial_number_padding=safe_int(
                ICP.get_param("assetz.serial_number_padding"), 5
            ),
            assetz_qr_code_size=safe_int(ICP.get_param("assetz.qr_code_size"), 200),
            assetz_eol_reminder_days=safe_int(
                ICP.get_param("assetz.eol_reminder_days"), 7
            ),
            assetz_default_useful_life=safe_int(
                ICP.get_param("assetz.default_useful_life"), 5
            ),
            assetz_ai_provider=ICP.get_param("assetz.ai_provider") or "none",
            assetz_openai_api_key=ICP.get_param("assetz.openai_api_key") or "",
            assetz_anthropic_api_key=ICP.get_param("assetz.anthropic_api_key") or "",
            assetz_ai_attribute_level=ICP.get_param("assetz.ai_attribute_level") or "2",
        )
        return res

    def action_apply_industry_preset(self):
        """Apply industry preset configurations when user clicks apply button.

        All features are enabled for all presets. Categories should be
        created manually by the user.
        """
        # Enable ALL features for any preset
        all_features_enabled = {
            "assetz_enable_qr_codes": True,
            "assetz_enable_serial_auto_generation": True,
            "assetz_enable_location_tracking": True,
            "assetz_enable_location_hierarchy": True,
            "assetz_enable_movement_logging": True,
            "assetz_enable_barcode_scanning": True,
            "assetz_enable_asset_issuance": True,
            "assetz_enable_asset_requests": True,
            "assetz_enable_category_approval": True,
            "assetz_enable_eol_tracking": True,
            "assetz_enable_eol_notifications": True,
            "assetz_enable_ai_recommendations": True,
            "assetz_enable_erp_import": True,
            "assetz_enable_purchase_requests": True,
            "assetz_auto_create_assets_from_po": False,
            "assetz_enable_warranty_tracking": True,
            "assetz_enable_maintenance_integration": True,
            "assetz_auto_determine_billing": True,
        }

        if self.assetz_industry_preset and self.assetz_industry_preset != "custom":
            # Enable all features
            self.write(all_features_enabled)

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
