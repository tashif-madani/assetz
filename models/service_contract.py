from datetime import timedelta

from odoo import api, fields, models


class AssetzServiceContract(models.Model):
    """Model for tracking warranty, AMC, and service contracts for assets."""

    _name = "assetz.service.contract"
    _description = "Service Contract"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "end_date desc, id desc"

    name = fields.Char(
        string="Contract Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )
    display_name_custom = fields.Char(
        string="Contract Name",
        required=True,
        tracking=True,
    )

    # Contract Type
    contract_type = fields.Selection(
        selection=[
            ("manufacturer_warranty", "Manufacturer Warranty"),
            ("extended_warranty", "Extended Warranty"),
            ("amc", "Annual Maintenance Contract"),
            ("service_agreement", "Service Agreement"),
        ],
        string="Contract Type",
        required=True,
        tracking=True,
    )

    # Provider/Vendor
    provider_id = fields.Many2one(
        comodel_name="res.partner",
        string="Provider/Vendor",
        required=True,
        domain="[('is_company', '=', True)]",
        tracking=True,
        help="OEM, extended warranty provider, or service vendor",
    )

    # Coverage Period
    start_date = fields.Date(
        string="Start Date",
        required=True,
        tracking=True,
    )
    end_date = fields.Date(
        string="End Date",
        required=True,
        tracking=True,
    )

    # Coverage Scope
    coverage_type = fields.Selection(
        selection=[
            ("parts_only", "Parts Only"),
            ("labor_only", "Labor Only"),
            ("comprehensive", "Comprehensive (Parts + Labor)"),
            ("custom", "Custom Coverage"),
        ],
        string="Coverage Type",
        required=True,
        default="comprehensive",
        tracking=True,
    )

    # Custom coverage percentages (for partial coverage)
    parts_coverage_percent = fields.Float(
        string="Parts Coverage %",
        default=100.0,
        help="Percentage of parts cost covered (0-100)",
    )
    labor_coverage_percent = fields.Float(
        string="Labor Coverage %",
        default=100.0,
        help="Percentage of labor cost covered (0-100)",
    )

    # Coverage Limits
    max_claims_per_year = fields.Integer(
        string="Max Claims/Year",
        default=0,
        help="0 means unlimited",
    )
    max_claim_value = fields.Monetary(
        string="Max Claim Value",
        currency_field="currency_id",
        default=0.0,
        help="Maximum value per claim (0 = unlimited)",
    )
    annual_limit = fields.Monetary(
        string="Annual Limit",
        currency_field="currency_id",
        default=0.0,
        help="Total annual coverage limit (0 = unlimited)",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # Deductible
    deductible_amount = fields.Monetary(
        string="Deductible",
        currency_field="currency_id",
        default=0.0,
        help="Amount to be paid by asset owner before coverage kicks in",
    )

    # Asset Linking - supports multiple patterns
    asset_ids = fields.Many2many(
        comodel_name="assetz.asset",
        relation="assetz_contract_asset_rel",
        column1="contract_id",
        column2="asset_id",
        string="Covered Assets",
    )
    category_id = fields.Many2one(
        comodel_name="assetz.category",
        string="Asset Category",
        help="If set, all assets in this category are covered",
    )
    apply_to_category = fields.Boolean(
        string="Apply to Entire Category",
        default=False,
        help="If checked, contract applies to all assets in selected category",
    )

    # Exclusions and Terms
    exclusion_ids = fields.One2many(
        comodel_name="assetz.contract.exclusion",
        inverse_name="contract_id",
        string="Exclusions",
    )
    terms_and_conditions = fields.Html(
        string="Terms & Conditions",
    )

    # Contract Document
    contract_document = fields.Binary(
        string="Contract Document",
    )
    contract_document_filename = fields.Char(
        string="Document Filename",
    )

    # Status
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    # Computed Fields
    is_valid = fields.Boolean(
        string="Currently Valid",
        compute="_compute_is_valid",
        store=True,
    )
    days_remaining = fields.Integer(
        string="Days Remaining",
        compute="_compute_days_remaining",
    )
    claims_this_year = fields.Integer(
        string="Claims This Year",
        compute="_compute_claims_stats",
    )
    total_claimed_this_year = fields.Monetary(
        string="Total Claimed This Year",
        compute="_compute_claims_stats",
        currency_field="currency_id",
    )
    remaining_annual_limit = fields.Monetary(
        string="Remaining Annual Limit",
        compute="_compute_claims_stats",
        currency_field="currency_id",
    )

    # Claims relationship
    claim_ids = fields.One2many(
        comodel_name="assetz.warranty.claim",
        inverse_name="contract_id",
        string="Claims",
    )
    claim_count = fields.Integer(
        string="Total Claims",
        compute="_compute_claim_count",
    )

    # Company
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )

    # Notes
    notes = fields.Text(string="Internal Notes")

    @api.model_create_multi
    def create(self, vals_list):
        """Generate contract reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.service.contract"
                ) or "New"
        return super().create(vals_list)

    @api.depends("start_date", "end_date", "state")
    def _compute_is_valid(self):
        """Check if contract is currently valid."""
        today = fields.Date.today()
        for contract in self:
            contract.is_valid = (
                contract.state == "active"
                and contract.start_date
                and contract.end_date
                and contract.start_date <= today <= contract.end_date
            )

    def _compute_days_remaining(self):
        """Calculate days until contract expiry."""
        today = fields.Date.today()
        for contract in self:
            if contract.end_date and contract.end_date >= today:
                contract.days_remaining = (contract.end_date - today).days
            else:
                contract.days_remaining = 0

    @api.depends("claim_ids", "claim_ids.state", "claim_ids.total_claimed_amount")
    def _compute_claims_stats(self):
        """Compute claims statistics for current year."""
        today = fields.Date.today()
        year_start = today.replace(month=1, day=1)
        for contract in self:
            year_claims = contract.claim_ids.filtered(
                lambda c: c.state in ("approved", "partially_approved", "paid")
                and c.create_date
                and c.create_date.date() >= year_start
            )
            contract.claims_this_year = len(year_claims)
            contract.total_claimed_this_year = sum(
                year_claims.mapped("total_claimed_amount")
            )
            if contract.annual_limit > 0:
                contract.remaining_annual_limit = (
                    contract.annual_limit - contract.total_claimed_this_year
                )
            else:
                contract.remaining_annual_limit = 0.0

    def _compute_claim_count(self):
        """Count total claims for this contract."""
        for contract in self:
            contract.claim_count = len(contract.claim_ids)

    def check_coverage(self, asset, cost_type="parts", amount=0.0):
        """
        Check if asset is covered and return coverage details.

        Args:
            asset: The assetz.asset record to check
            cost_type: 'parts' or 'labor'
            amount: The cost amount to check coverage for

        Returns dict:
        {
            'is_covered': bool,
            'coverage_percent': float,
            'max_claimable': float,
            'reason': str,
        }
        """
        self.ensure_one()
        result = {
            "is_covered": False,
            "coverage_percent": 0.0,
            "max_claimable": 0.0,
            "reason": "",
        }

        # Check validity
        if not self.is_valid:
            result["reason"] = "Contract is not active or has expired"
            return result

        # Check asset is covered
        is_asset_covered = asset in self.asset_ids or (
            self.apply_to_category and asset.category_id == self.category_id
        )
        if not is_asset_covered:
            result["reason"] = "Asset is not covered under this contract"
            return result

        # Check claims limit
        if (
            self.max_claims_per_year > 0
            and self.claims_this_year >= self.max_claims_per_year
        ):
            result["reason"] = "Maximum claims per year exceeded"
            return result

        # Check annual limit
        if self.annual_limit > 0 and self.remaining_annual_limit <= 0:
            result["reason"] = "Annual coverage limit exhausted"
            return result

        # Determine coverage percentage based on coverage type
        if cost_type == "parts":
            if self.coverage_type in ("parts_only", "comprehensive", "custom"):
                result["coverage_percent"] = self.parts_coverage_percent
            else:
                result["reason"] = "Parts not covered under this contract"
                return result
        elif cost_type == "labor":
            if self.coverage_type in ("labor_only", "comprehensive", "custom"):
                result["coverage_percent"] = self.labor_coverage_percent
            else:
                result["reason"] = "Labor not covered under this contract"
                return result

        # Calculate max claimable amount
        claimable = amount * (result["coverage_percent"] / 100)

        # Apply per-claim limit
        if self.max_claim_value > 0:
            claimable = min(claimable, self.max_claim_value)

        # Apply remaining annual limit
        if self.annual_limit > 0:
            claimable = min(claimable, self.remaining_annual_limit)

        result["is_covered"] = True
        result["max_claimable"] = claimable
        return result

    def action_activate(self):
        """Activate the contract."""
        self.write({"state": "active"})

    def action_cancel(self):
        """Cancel the contract."""
        self.write({"state": "cancelled"})

    def action_set_draft(self):
        """Reset contract to draft."""
        self.write({"state": "draft"})

    def action_view_claims(self):
        """View warranty claims for this contract."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"Claims - {self.display_name_custom}",
            "res_model": "assetz.warranty.claim",
            "view_mode": "list,form",
            "domain": [("contract_id", "=", self.id)],
            "context": {"default_contract_id": self.id},
        }

    @api.model
    def _cron_check_contract_expiry(self):
        """Cron to check and update expired contracts, send reminders."""
        today = fields.Date.today()

        # Mark expired contracts
        expired = self.search(
            [
                ("state", "=", "active"),
                ("end_date", "<", today),
            ]
        )
        expired.write({"state": "expired"})

        # Send expiry reminders
        reminder_days = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("assetz.contract_expiry_reminder_days", "30")
        )
        reminder_date = today + timedelta(days=reminder_days)
        expiring_soon = self.search(
            [
                ("state", "=", "active"),
                ("end_date", "<=", reminder_date),
                ("end_date", ">=", today),
            ]
        )

        for contract in expiring_soon:
            contract.message_post(
                body=f"Contract {contract.name} ({contract.display_name_custom}) "
                f"will expire on {contract.end_date}. "
                f"Please review and renew if needed.",
                subject="Contract Expiry Reminder",
                message_type="notification",
            )


class AssetzContractExclusion(models.Model):
    """Model for tracking coverage exclusions on service contracts."""

    _name = "assetz.contract.exclusion"
    _description = "Contract Exclusion"
    _order = "sequence, id"

    contract_id = fields.Many2one(
        comodel_name="assetz.service.contract",
        string="Contract",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)

    exclusion_type = fields.Selection(
        selection=[
            ("part_type", "Part Type"),
            ("damage_type", "Damage Type"),
            ("condition", "Condition"),
            ("custom", "Custom"),
        ],
        string="Exclusion Type",
        required=True,
        default="custom",
    )
    name = fields.Char(
        string="Description",
        required=True,
        help="e.g., 'Cosmetic damage', 'Consumables', 'User-induced damage'",
    )
    notes = fields.Text(string="Details")
