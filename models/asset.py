import base64
import io
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from .industry_examples import INDUSTRY_EXAMPLES

_logger = logging.getLogger(__name__)

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False
    _logger.warning("qrcode library not installed. QR code generation will be disabled.")


class Asset(models.Model):
    """Model for tracking organizational assets."""

    _name = "assetz.asset"
    _description = "Asset"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    # Industry-specific example text (computed from settings)
    example_asset_name = fields.Char(
        string="Example Asset Name",
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
            rec.example_asset_name = f"e.g. {examples.get('asset_name', '')}"

    name = fields.Char(
        string="Asset Name",
        required=True,
        tracking=True,
    )
    code = fields.Char(
        string="Asset Code",
        copy=False,
        readonly=True,
        default="New",
    )
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    # Category and Classification (using custom category)
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Category",
        tracking=True,
    )
    tag_ids = fields.Many2many(
        comodel_name="assetz.asset.tag",
        string="Tags",
    )

    # Dynamic Attributes
    attribute_value_ids = fields.One2many(
        comodel_name="assetz.asset.attribute.value",
        inverse_name="asset_id",
        string="Attributes",
    )

    # Status
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending_approval", "Pending Approval"),
            ("active", "Active"),
            ("maintenance", "Under Maintenance"),
            ("retired", "Retired"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    # Approval workflow
    approval_state = fields.Selection(
        selection=[
            ("not_required", "Not Required"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Approval Status",
        default="not_required",
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
        tracking=True,
    )
    approved_date = fields.Datetime(
        string="Approval Date",
        tracking=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
    )

    # Issue State (for asset issuance workflow)
    issue_state = fields.Selection(
        selection=[
            ("available", "Available"),
            ("issued", "Issued"),
            ("reserved", "Reserved"),
            ("in_transit", "In Transit"),
        ],
        string="Issue Status",
        default="available",
        tracking=True,
    )
    current_holder_type = fields.Selection(
        selection=[
            ("employee", "Employee"),
            ("user", "System User"),
            ("partner", "Contact"),
            ("department", "Department"),
            ("location", "Location"),
            ("project", "Project"),
            ("cost_center", "Cost Center"),
            ("other", "Other"),
        ],
        string="Holder Type",
    )
    current_holder_display = fields.Char(
        string="Current Holder",
        tracking=True,
    )
    issue_date = fields.Date(
        string="Issue Date",
    )
    expected_return_date = fields.Date(
        string="Expected Return Date",
    )
    last_issue_order_id = fields.Many2one(
        comodel_name="assetz.issue.order",
        string="Last Issue Order",
    )

    # QR Code
    qr_code = fields.Binary(
        string="QR Code",
        compute="_compute_qr_code",
        store=True,
    )
    qr_code_data = fields.Char(
        string="QR Data",
        compute="_compute_qr_code",
        store=True,
    )

    # Acquisition Information
    acquisition_date = fields.Date(
        string="Acquisition Date",
        tracking=True,
    )
    acquisition_cost = fields.Monetary(
        string="Acquisition Cost",
        currency_field="currency_id",
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )
    supplier_id = fields.Many2one(
        comodel_name="res.partner",
        string="Supplier",
        domain="[('is_company', '=', True)]",
    )
    purchase_request_id = fields.Many2one(
        comodel_name="assetz.purchase.request",
        string="Purchase Request",
        help="Purchase request from which this asset was created",
    )
    source_asset_request_id = fields.Many2one(
        comodel_name="assetz.asset.request",
        string="Source Asset Request",
        help="Original asset request that led to the purchase of this asset",
    )

    # Location and Assignment
    location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Location",
        required=True,
        tracking=True,
    )
    location_display = fields.Char(
        related="location_id.complete_name",
        string="Location Name",
        store=True,
    )
    assigned_to_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned To",
        tracking=True,
    )
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string="Department",
        tracking=True,
    )

    # Technical Information
    serial_number = fields.Char(string="Serial Number")
    model = fields.Char(string="Model")
    manufacturer = fields.Char(string="Manufacturer")
    warranty_expiry_date = fields.Date(string="Warranty Expiry Date")

    # Service Contract relationship
    contract_ids = fields.Many2many(
        comodel_name="assetz.service.contract",
        relation="assetz_contract_asset_rel",
        column1="asset_id",
        column2="contract_id",
        string="Service Contracts",
    )
    active_contract_count = fields.Integer(
        string="Active Contracts",
        compute="_compute_contract_status",
    )

    # Computed warranty status
    warranty_status = fields.Selection(
        selection=[
            ("no_warranty", "No Warranty"),
            ("under_warranty", "Under Warranty"),
            ("warranty_expiring", "Warranty Expiring Soon"),
            ("warranty_expired", "Warranty Expired"),
        ],
        string="Warranty Status",
        compute="_compute_warranty_status_from_contracts",
        store=True,
    )
    primary_warranty_id = fields.Many2one(
        comodel_name="assetz.service.contract",
        string="Primary Warranty",
        compute="_compute_warranty_status_from_contracts",
        store=True,
    )
    warranty_days_remaining = fields.Integer(
        string="Warranty Days Left",
        compute="_compute_warranty_status_from_contracts",
    )
    warranty_end_date = fields.Date(
        string="Warranty End Date",
        compute="_compute_warranty_status_from_contracts",
        store=True,
        help="Auto-populated from active warranty contracts",
    )

    # Maintenance order link (standalone maintenance system)
    maintenance_order_ids = fields.One2many(
        comodel_name="assetz.maintenance.order",
        inverse_name="asset_id",
        string="Maintenance Orders",
    )
    maintenance_count = fields.Integer(
        string="Maintenance Count",
        compute="_compute_maintenance_count",
    )

    # Service / Rental orders
    order_line_ids = fields.One2many(
        comodel_name="assetz.order.line",
        inverse_name="asset_id",
        string="Order Lines",
    )
    order_count = fields.Integer(
        string="Order Count",
        compute="_compute_order_count",
    )
    last_maintenance_date = fields.Date(
        string="Last Maintenance",
        tracking=True,
        help="Date of last completed maintenance",
    )
    next_maintenance_date = fields.Date(
        string="Next Maintenance",
        compute="_compute_next_maintenance",
        store=True,
        help="Next scheduled maintenance date",
    )

    # Usage Tracking (for usage-based maintenance)
    current_usage_hours = fields.Float(
        string="Operating Hours",
        tracking=True,
        help="Current total operating hours",
    )
    current_usage_mileage = fields.Float(
        string="Mileage (km)",
        tracking=True,
        help="Current total mileage in kilometers",
    )
    current_usage_cycles = fields.Integer(
        string="Cycles/Operations",
        tracking=True,
        help="Current total cycles or operations count",
    )

    # Depreciation (basic)
    useful_life_years = fields.Integer(string="Useful Life (Years)")
    salvage_value = fields.Monetary(
        string="Salvage Value",
        currency_field="currency_id",
    )

    # Company (multi-company support)
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # Ownership Information
    ownership_type = fields.Selection(
        selection=[
            ("company", "Company Owned"),
            ("customer", "Customer Owned"),
        ],
        string="Ownership",
        default="company",
        required=True,
        tracking=True,
        help="Indicates whether this asset is owned by the company or by a customer",
    )
    owner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer Owner",
        tracking=True,
        domain="[('is_company', '=', True)]",
        help="If customer owned, specify the customer who owns this asset",
    )
    is_customer_owned = fields.Boolean(
        string="Is Customer Owned",
        compute="_compute_is_customer_owned",
        store=True,
    )

    # End of Life (EOL) Tracking
    eol_enabled = fields.Boolean(
        string="EOL Tracking Enabled",
        default=True,
    )
    eol_date = fields.Date(
        string="End of Life Date",
        tracking=True,
        help="Date when this asset should be retired or replaced",
    )
    eol_reason = fields.Selection(
        selection=[
            ("age", "Age/Depreciation"),
            ("condition", "Poor Condition"),
            ("obsolete", "Obsolete/Outdated"),
            ("compliance", "Compliance/Regulatory"),
            ("upgrade", "Technology Upgrade"),
            ("other", "Other"),
        ],
        string="EOL Reason",
    )
    eol_notes = fields.Text(
        string="EOL Notes",
    )
    is_eol_due = fields.Boolean(
        string="EOL Due",
        compute="_compute_is_eol_due",
        store=True,
        help="True if EOL date has passed or is within reminder period",
    )
    eol_reminder_sent = fields.Boolean(
        string="EOL Reminder Sent",
        default=False,
    )

    # AI Recommendations
    ai_suggested_eol = fields.Date(
        string="AI Suggested EOL",
        help="EOL date suggested by AI analysis",
    )
    ai_eol_confidence = fields.Float(
        string="AI Confidence %",
        help="Confidence level of the AI suggestion",
    )
    ai_eol_factors = fields.Text(
        string="AI Analysis",
        help="Factors considered in AI recommendation",
    )
    ai_last_analysis_date = fields.Datetime(
        string="Last AI Analysis",
    )

    # Computed Fields
    age_days = fields.Integer(
        string="Age (Days)",
        compute="_compute_age_days",
        store=True,
    )
    days_until_eol = fields.Integer(
        string="Days Until EOL",
        compute="_compute_days_until_eol",
    )

    @api.depends("acquisition_date")
    def _compute_age_days(self):
        """Compute the age of the asset in days."""
        today = fields.Date.today()
        for asset in self:
            if asset.acquisition_date:
                delta = today - asset.acquisition_date
                asset.age_days = delta.days
            else:
                asset.age_days = 0

    @api.depends("ownership_type")
    def _compute_is_customer_owned(self):
        """Compute if asset is customer owned."""
        for asset in self:
            asset.is_customer_owned = asset.ownership_type == "customer"

    def _compute_days_until_eol(self):
        """Compute days remaining until EOL date."""
        today = fields.Date.today()
        for asset in self:
            if asset.eol_date:
                delta = asset.eol_date - today
                asset.days_until_eol = delta.days
            else:
                asset.days_until_eol = 0

    @api.depends("eol_date", "eol_enabled")
    def _compute_is_eol_due(self):
        """Check if EOL date is due or approaching."""
        today = fields.Date.today()
        reminder_days = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "assetz.eol_reminder_days", "7"
            )
        )
        for asset in self:
            if asset.eol_enabled and asset.eol_date:
                from datetime import timedelta
                reminder_date = asset.eol_date - timedelta(days=reminder_days)
                asset.is_eol_due = today >= reminder_date
            else:
                asset.is_eol_due = False

    def _compute_contract_status(self):
        """Count active contracts."""
        for asset in self:
            active_contracts = asset.contract_ids.filtered(lambda c: c.is_valid)
            asset.active_contract_count = len(active_contracts)

    @api.depends(
        "contract_ids",
        "contract_ids.is_valid",
        "contract_ids.end_date",
        "contract_ids.contract_type",
        "warranty_expiry_date",
    )
    def _compute_warranty_status_from_contracts(self):
        """Compute warranty status from contracts or legacy field."""
        today = fields.Date.today()
        reminder_days = 30  # Days before expiry to show warning

        for asset in self:
            # First check service contracts
            active_warranties = asset.contract_ids.filtered(
                lambda c: c.is_valid
                and c.contract_type in ("manufacturer_warranty", "extended_warranty")
            )

            if active_warranties:
                # Find primary (earliest ending active warranty)
                primary = active_warranties.sorted("end_date")[0]
                asset.primary_warranty_id = primary.id
                asset.warranty_end_date = primary.end_date
                asset.warranty_days_remaining = (primary.end_date - today).days

                if asset.warranty_days_remaining <= reminder_days:
                    asset.warranty_status = "warranty_expiring"
                else:
                    asset.warranty_status = "under_warranty"
            elif asset.warranty_expiry_date:
                # Fall back to legacy warranty_expiry_date field
                asset.primary_warranty_id = False
                asset.warranty_end_date = asset.warranty_expiry_date
                days_remaining = (asset.warranty_expiry_date - today).days
                asset.warranty_days_remaining = days_remaining

                if days_remaining < 0:
                    asset.warranty_status = "warranty_expired"
                elif days_remaining <= reminder_days:
                    asset.warranty_status = "warranty_expiring"
                else:
                    asset.warranty_status = "under_warranty"
            else:
                asset.primary_warranty_id = False
                asset.warranty_end_date = False
                asset.warranty_days_remaining = 0
                asset.warranty_status = "no_warranty"

    def _compute_maintenance_count(self):
        """Count maintenance orders for this asset."""
        for asset in self:
            asset.maintenance_count = len(asset.maintenance_order_ids)

    def _compute_order_count(self):
        for asset in self:
            asset.order_count = len(asset.order_line_ids.mapped("order_id"))

    @api.depends("maintenance_order_ids", "maintenance_order_ids.scheduled_date", "maintenance_order_ids.state")
    def _compute_next_maintenance(self):
        """Compute next scheduled maintenance date."""
        for asset in self:
            pending_orders = asset.maintenance_order_ids.filtered(
                lambda o: o.state not in ("completed", "cancelled") and o.scheduled_date
            ).sorted("scheduled_date")
            asset.next_maintenance_date = pending_orders[0].scheduled_date if pending_orders else False

    @api.depends("code", "name", "serial_number", "category_id")
    def _compute_qr_code(self):
        """Generate QR code containing a URL that opens asset details when scanned."""
        if not HAS_QRCODE:
            for asset in self:
                asset.qr_code = False
                asset.qr_code_data = False
            return

        qr_size = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "assetz.qr_code_size", "200"
            )
        )

        # Get the base URL for the Odoo instance
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

        for asset in self:
            # Skip QR generation for unsaved records (NewId) or records without a code
            if not asset.id or not isinstance(asset.id, int) or not asset.code or asset.code == "New":
                asset.qr_code = False
                asset.qr_code_data = False
                continue

            # Create QR data as URL - when scanned, this will open the asset details page
            qr_url = f"{base_url}/assetz/asset/{asset.id}"
            asset.qr_code_data = qr_url

            # Generate QR code image
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(qr_url)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")

            # Resize to configured size
            img = img.resize((qr_size, qr_size))

            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            asset.qr_code = base64.b64encode(buffer.getvalue())

    @api.model_create_multi
    def create(self, vals_list):
        """Generate asset code on creation."""
        for vals in vals_list:
            if vals.get("code", "New") == "New":
                vals["code"] = self.env["ir.sequence"].next_by_code(
                    "assetz.asset"
                ) or "New"

            # Auto-generate serial number if enabled
            auto_serial = self.env["ir.config_parameter"].sudo().get_param(
                "assetz.enable_serial_auto_generation", "True"
            )
            if auto_serial == "True" and not vals.get("serial_number"):
                prefix = self.env["ir.config_parameter"].sudo().get_param(
                    "assetz.serial_number_prefix", "AST"
                )
                padding = int(self.env["ir.config_parameter"].sudo().get_param(
                    "assetz.serial_number_padding", "5"
                ))
                sequence = self.env["ir.sequence"].next_by_code("assetz.asset.serial")
                if sequence:
                    vals["serial_number"] = f"{prefix}{sequence.zfill(padding)}"

        return super().create(vals_list)

    @api.onchange("category_id")
    def _onchange_category_id(self):
        """Auto-populate attribute values when category is selected."""
        if self.category_id:
            # Get existing attribute IDs that belong to this category
            existing_attr_ids = set()
            for val in self.attribute_value_ids:
                if val.attribute_id and val.attribute_id.category_id == self.category_id:
                    existing_attr_ids.add(val.attribute_id.id)

            # Create new attribute values for all category attributes not yet added
            new_vals = []
            for attr in self.category_id.attribute_ids:
                if attr.id not in existing_attr_ids:
                    attr_data = {"attribute_id": attr.id}

                    # Only set default value if explicitly defined
                    if attr.attribute_type == "selection":
                        # For dropdown, only set if there's an option marked as default
                        default_opt = attr.option_ids.filtered(lambda o: o.is_default)
                        if default_opt:
                            attr_data["value_selection_id"] = default_opt[0].id
                            attr_data["value"] = default_opt[0].name
                    elif attr.default_value:
                        # For other types, only set if default_value is defined
                        attr_data["value"] = attr.default_value

                    new_vals.append((0, 0, attr_data))

            # Clear all existing and set new ones
            if new_vals or self.attribute_value_ids:
                # Keep existing values for current category, add new ones
                keep_vals = []
                for val in self.attribute_value_ids:
                    if val.attribute_id and val.attribute_id.category_id == self.category_id:
                        if val.id:
                            keep_vals.append((4, val.id))
                        else:
                            # For new unsaved records, recreate them
                            recreate_data = {
                                "attribute_id": val.attribute_id.id,
                                "value": val.value or "",
                            }
                            if val.attribute_type == "selection" and val.value_selection_id:
                                recreate_data["value_selection_id"] = val.value_selection_id.id
                            keep_vals.append((0, 0, recreate_data))

                self.attribute_value_ids = [(5, 0, 0)] + keep_vals + new_vals

            # Apply category defaults
            if self.category_id.default_useful_life and not self.useful_life_years:
                self.useful_life_years = self.category_id.default_useful_life
        else:
            # Category cleared - remove all attribute values
            self.attribute_value_ids = [(5, 0, 0)]

    def action_activate(self):
        """Activate the asset."""
        for asset in self:
            # Check if category requires approval
            if asset.category_id and asset.category_id.require_approval:
                if asset.approval_state != "approved":
                    asset.write({
                        "state": "pending_approval",
                        "approval_state": "pending",
                    })
                    continue
            asset.write({"state": "active"})

    def action_approve(self):
        """Approve the asset (for category approval workflow)."""
        self.write({
            "approval_state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_date": fields.Datetime.now(),
            "state": "active",
        })

    def action_reject(self):
        """Reject the asset approval."""
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.asset.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_asset_id": self.id},
        }

    def action_maintenance(self):
        """Set asset to maintenance status."""
        for asset in self:
            # Log movement if enabled
            if self.env["ir.config_parameter"].sudo().get_param(
                "assetz.enable_movement_logging", "False"
            ) == "True":
                self.env["assetz.asset.movement"].create({
                    "asset_id": asset.id,
                    "from_location_id": asset.location_id.id if asset.location_id else False,
                    "movement_type": "maintenance",
                    "reason": "Asset sent for maintenance",
                })
        self.write({"state": "maintenance"})

    def action_retire(self):
        """Retire the asset."""
        for asset in self:
            # Log movement if enabled
            if self.env["ir.config_parameter"].sudo().get_param(
                "assetz.enable_movement_logging", "False"
            ) == "True":
                self.env["assetz.asset.movement"].create({
                    "asset_id": asset.id,
                    "from_location_id": asset.location_id.id if asset.location_id else False,
                    "movement_type": "disposal",
                    "reason": "Asset retired",
                })
        self.write({"state": "retired"})

    def action_draft(self):
        """Reset asset to draft status."""
        self.write({
            "state": "draft",
            "approval_state": "not_required",
            "approved_by_id": False,
            "approved_date": False,
            "rejection_reason": False,
        })

    def action_request_ai_eol(self):
        """Request AI-based EOL recommendation."""
        ai_provider = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.ai_provider", "none"
        )
        if ai_provider == "none":
            raise UserError("AI recommendations are not enabled. Please configure an AI provider in settings.")

        for asset in self:
            asset._get_ai_eol_recommendation()

    def _get_ai_eol_recommendation(self):
        """Get EOL recommendation from AI provider."""
        self.ensure_one()

        ai_provider = self.env["ir.config_parameter"].sudo().get_param(
            "assetz.ai_provider", "none"
        )

        if ai_provider == "openai":
            self._get_openai_eol_recommendation()
        elif ai_provider == "anthropic":
            self._get_anthropic_eol_recommendation()

    def _get_openai_eol_recommendation(self):
        """Get EOL recommendation from OpenAI."""
        try:
            import openai
        except ImportError:
            raise UserError("OpenAI library not installed. Please install with: pip install openai")

        api_key = self.env["ir.config_parameter"].sudo().get_param("assetz.openai_api_key")
        if not api_key:
            raise UserError("OpenAI API key not configured.")

        # Prepare asset data for AI analysis
        asset_data = {
            "name": self.name,
            "category": self.category_id.name if self.category_id else "Unknown",
            "acquisition_date": str(self.acquisition_date) if self.acquisition_date else "Unknown",
            "age_days": self.age_days,
            "useful_life_years": self.useful_life_years or 5,
            "manufacturer": self.manufacturer or "Unknown",
            "model": self.model or "Unknown",
            "current_state": self.state,
        }

        prompt = f"""Analyze this asset and suggest an End of Life (EOL) date.

Asset Information:
- Name: {asset_data['name']}
- Category: {asset_data['category']}
- Acquisition Date: {asset_data['acquisition_date']}
- Current Age (days): {asset_data['age_days']}
- Expected Useful Life: {asset_data['useful_life_years']} years
- Manufacturer: {asset_data['manufacturer']}
- Model: {asset_data['model']}
- Current State: {asset_data['current_state']}

Please provide:
1. A suggested EOL date in YYYY-MM-DD format
2. A confidence percentage (0-100)
3. Key factors considered in your analysis

Respond in JSON format:
{{"suggested_eol_date": "YYYY-MM-DD", "confidence": 85, "factors": "List of factors..."}}"""

        try:
            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )

            result_text = response.choices[0].message.content
            result = json.loads(result_text)

            self.write({
                "ai_suggested_eol": result.get("suggested_eol_date"),
                "ai_eol_confidence": result.get("confidence", 0),
                "ai_eol_factors": result.get("factors", ""),
                "ai_last_analysis_date": fields.Datetime.now(),
            })
        except Exception as e:
            _logger.error(f"OpenAI EOL analysis failed: {e}")
            raise UserError(f"AI analysis failed: {str(e)}")

    def _get_anthropic_eol_recommendation(self):
        """Get EOL recommendation from Anthropic Claude."""
        # Similar implementation for Anthropic
        raise UserError("Anthropic integration not yet implemented.")

    def action_accept_ai_eol(self):
        """Accept the AI-suggested EOL date."""
        for asset in self:
            if asset.ai_suggested_eol:
                asset.eol_date = asset.ai_suggested_eol

    def action_view_movements(self):
        """Open movements view filtered by this asset."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Movements - {self.name}",
            "res_model": "assetz.asset.movement",
            "view_mode": "list,form",
            "views": [(False, "list"), (False, "form")],
            "domain": [("asset_id", "=", self.id)],
            "context": {"default_asset_id": self.id},
        }

    def action_view_contracts(self):
        """View service contracts for this asset."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Contracts - {self.name}",
            "res_model": "assetz.service.contract",
            "view_mode": "list,form",
            "domain": [("asset_ids", "in", self.id)],
            "context": {"default_asset_ids": [(4, self.id)]},
        }

    def action_view_maintenance(self):
        """View maintenance orders for this asset."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Maintenance - {self.name}",
            "res_model": "assetz.maintenance.order",
            "view_mode": "list,form,kanban",
            "domain": [("asset_id", "=", self.id)],
            "context": {"default_asset_id": self.id},
        }

    def action_create_maintenance_order(self):
        """Create a new maintenance order for this asset."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Create Maintenance Order",
            "res_model": "assetz.maintenance.order",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_asset_id": self.id,
                "default_maintenance_type": "corrective",
            },
        }

    def action_view_orders(self):
        """View Service/Rental orders for this asset."""
        self.ensure_one()
        order_ids = self.order_line_ids.mapped("order_id").ids
        return {
            "type": "ir.actions.act_window",
            "name": f"Orders - {self.name}",
            "res_model": "assetz.order",
            "view_mode": "list,form,kanban",
            "domain": [("id", "in", order_ids)],
        }

    @api.model
    def _cron_eol_reminder(self):
        """Cron job to send EOL reminders."""
        if self.env["ir.config_parameter"].sudo().get_param(
            "assetz.enable_eol_notifications", "True"
        ) != "True":
            return

        reminder_days = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "assetz.eol_reminder_days", "7"
            )
        )

        from datetime import timedelta
        today = fields.Date.today()
        reminder_date = today + timedelta(days=reminder_days)

        # Find assets with EOL coming up
        assets = self.search([
            ("eol_enabled", "=", True),
            ("eol_date", "<=", reminder_date),
            ("eol_date", ">=", today),
            ("eol_reminder_sent", "=", False),
            ("state", "!=", "retired"),
        ])

        for asset in assets:
            # Send notification via mail.thread
            asset.message_post(
                body=f"EOL Reminder: Asset {asset.name} ({asset.code}) is approaching "
                     f"its End of Life date ({asset.eol_date}). Please plan for replacement or retirement.",
                subject=f"EOL Reminder: {asset.name}",
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

            # Create activity for assigned user
            if asset.assigned_to_id:
                asset.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=asset.assigned_to_id.id,
                    summary=f"EOL approaching for {asset.name}",
                    note=f"Asset {asset.code} has EOL date {asset.eol_date}",
                )

            asset.eol_reminder_sent = True

        _logger.info(f"Sent EOL reminders for {len(assets)} assets")


class AssetTag(models.Model):
    """Tags for categorizing assets."""

    _name = "assetz.asset.tag"
    _description = "Asset Tag"

    name = fields.Char(string="Tag Name", required=True)
    color = fields.Integer(string="Color")


class AssetRejectWizard(models.TransientModel):
    """Wizard for rejecting asset approval with reason."""

    _name = "assetz.asset.reject.wizard"
    _description = "Asset Rejection Wizard"

    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        """Reject the asset with the provided reason."""
        self.asset_id.write({
            "approval_state": "rejected",
            "rejection_reason": self.reason,
            "state": "draft",
        })
        return {"type": "ir.actions.act_window_close"}
