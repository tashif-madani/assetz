from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetzWarrantyClaim(models.Model):
    """Model for tracking warranty and contract claims."""

    _name = "assetz.warranty.claim"
    _description = "Warranty/Contract Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        string="Claim Reference",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    # Links
    maintenance_order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Work Order",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    contract_id = fields.Many2one(
        comodel_name="assetz.service.contract",
        string="Service Contract",
        required=True,
        tracking=True,
        domain="[('is_valid', '=', True)]",
    )
    asset_id = fields.Many2one(
        comodel_name="assetz.asset",
        string="Asset",
        required=True,
        tracking=True,
    )

    # Claim Details
    claim_date = fields.Date(
        string="Claim Date",
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    description = fields.Text(
        string="Claim Description",
        required=True,
    )

    # Cost Breakdown
    line_ids = fields.One2many(
        comodel_name="assetz.warranty.claim.line",
        inverse_name="claim_id",
        string="Claim Lines",
    )

    # Totals
    total_parts_cost = fields.Monetary(
        string="Total Parts Cost",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    total_labor_cost = fields.Monetary(
        string="Total Labor Cost",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    total_cost = fields.Monetary(
        string="Total Cost",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )

    # Claimed amounts (what's covered)
    parts_claimed_amount = fields.Monetary(
        string="Parts Claimed",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )
    labor_claimed_amount = fields.Monetary(
        string="Labor Claimed",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )
    total_claimed_amount = fields.Monetary(
        string="Total Claimed",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )

    # Customer responsibility (uncovered portions)
    customer_parts_amount = fields.Monetary(
        string="Customer Parts Amount",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )
    customer_labor_amount = fields.Monetary(
        string="Customer Labor Amount",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )
    customer_total_amount = fields.Monetary(
        string="Customer Total",
        compute="_compute_claimed_amounts",
        store=True,
        currency_field="currency_id",
    )

    # Deductible
    deductible_applied = fields.Monetary(
        string="Deductible Applied",
        currency_field="currency_id",
        default=0.0,
    )

    currency_id = fields.Many2one(
        comodel_name="res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
    )

    # Status Workflow
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("submitted", "Submitted to Provider"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("partially_approved", "Partially Approved"),
            ("rejected", "Rejected"),
            ("paid", "Paid/Settled"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    # Provider Response
    provider_reference = fields.Char(
        string="Provider Claim Number",
        tracking=True,
    )
    provider_response = fields.Text(
        string="Provider Response",
    )
    approved_amount = fields.Monetary(
        string="Approved Amount",
        currency_field="currency_id",
        help="Amount approved by provider (may differ from claimed)",
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
    )

    # Financial Integration
    vendor_bill_id = fields.Many2one(
        comodel_name="account.move",
        string="Vendor Credit/Payment",
        domain="[('move_type', 'in', ['in_refund', 'in_invoice'])]",
    )
    customer_invoice_id = fields.Many2one(
        comodel_name="account.move",
        string="Customer Invoice",
        domain="[('move_type', '=', 'out_invoice')]",
    )
    purchase_order_id = fields.Many2one(
        comodel_name="purchase.order",
        string="Replacement PO",
        help="Purchase order for replacement parts from vendor",
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
        """Generate claim reference on creation."""
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "assetz.warranty.claim"
                ) or "New"
        return super().create(vals_list)

    @api.depends("line_ids", "line_ids.amount", "line_ids.line_type")
    def _compute_totals(self):
        """Compute total parts and labor costs."""
        for claim in self:
            parts_lines = claim.line_ids.filtered(lambda ln: ln.line_type == "parts")
            labor_lines = claim.line_ids.filtered(lambda ln: ln.line_type == "labor")
            claim.total_parts_cost = sum(parts_lines.mapped("amount"))
            claim.total_labor_cost = sum(labor_lines.mapped("amount"))
            claim.total_cost = claim.total_parts_cost + claim.total_labor_cost

    @api.depends(
        "total_parts_cost",
        "total_labor_cost",
        "contract_id",
        "asset_id",
        "contract_id.parts_coverage_percent",
        "contract_id.labor_coverage_percent",
        "contract_id.deductible_amount",
    )
    def _compute_claimed_amounts(self):
        """Calculate claimed vs customer responsibility amounts."""
        for claim in self:
            if not claim.contract_id or not claim.asset_id:
                claim.parts_claimed_amount = 0.0
                claim.labor_claimed_amount = 0.0
                claim.total_claimed_amount = 0.0
                claim.customer_parts_amount = claim.total_parts_cost
                claim.customer_labor_amount = claim.total_labor_cost
                claim.customer_total_amount = claim.total_cost
                continue

            contract = claim.contract_id

            # Parts coverage
            parts_coverage = contract.check_coverage(
                claim.asset_id, "parts", claim.total_parts_cost
            )
            if parts_coverage["is_covered"]:
                claim.parts_claimed_amount = parts_coverage["max_claimable"]
            else:
                claim.parts_claimed_amount = 0.0

            # Labor coverage
            labor_coverage = contract.check_coverage(
                claim.asset_id, "labor", claim.total_labor_cost
            )
            if labor_coverage["is_covered"]:
                claim.labor_claimed_amount = labor_coverage["max_claimable"]
            else:
                claim.labor_claimed_amount = 0.0

            # Apply deductible
            total_claimable = claim.parts_claimed_amount + claim.labor_claimed_amount
            deductible = min(contract.deductible_amount, total_claimable)
            claim.deductible_applied = deductible

            claim.total_claimed_amount = total_claimable - deductible

            # Customer responsibility
            claim.customer_parts_amount = (
                claim.total_parts_cost - claim.parts_claimed_amount
            )
            claim.customer_labor_amount = (
                claim.total_labor_cost - claim.labor_claimed_amount
            )
            claim.customer_total_amount = (
                claim.customer_parts_amount
                + claim.customer_labor_amount
                + claim.deductible_applied
            )

    def action_submit(self):
        """Submit claim to provider."""
        for claim in self:
            if not claim.line_ids:
                raise UserError("Please add claim lines before submitting.")
            claim.state = "submitted"
            # Create activity for tracking
            claim.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=f"Follow up on warranty claim {claim.name}",
                note=f"Claim submitted to {claim.contract_id.provider_id.name}",
            )

    def action_mark_under_review(self):
        """Mark as under review by provider."""
        self.write({"state": "under_review"})

    def action_approve(self):
        """Approve the claim."""
        for claim in self:
            if not claim.approved_amount:
                claim.approved_amount = claim.total_claimed_amount
            claim.state = "approved"

    def action_partial_approve(self):
        """Partially approve the claim (opens wizard)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Partial Approval",
            "res_model": "assetz.claim.partial.approve.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_claim_id": self.id},
        }

    def action_reject(self):
        """Reject the claim (opens wizard for reason)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Rejection Reason",
            "res_model": "assetz.claim.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_claim_id": self.id},
        }

    def action_cancel(self):
        """Cancel the claim."""
        self.write({"state": "cancelled"})

    def action_set_draft(self):
        """Reset claim to draft."""
        self.write({"state": "draft"})

    def action_create_vendor_credit(self):
        """Create vendor credit note for approved claim."""
        self.ensure_one()
        if self.state not in ("approved", "partially_approved"):
            raise UserError("Claim must be approved first.")

        if self.vendor_bill_id:
            raise UserError("A vendor credit already exists for this claim.")

        # Create credit note from provider
        move_vals = {
            "move_type": "in_refund",
            "partner_id": self.contract_id.provider_id.id,
            "invoice_date": fields.Date.today(),
            "ref": f"Warranty Claim: {self.name}",
            "invoice_line_ids": [
                (
                    0,
                    0,
                    {
                        "name": f"Warranty claim settlement - {self.name}",
                        "quantity": 1,
                        "price_unit": self.approved_amount
                        or self.total_claimed_amount,
                    },
                )
            ],
        }

        credit_note = self.env["account.move"].create(move_vals)
        self.vendor_bill_id = credit_note.id

        return {
            "type": "ir.actions.act_window",
            "name": "Vendor Credit Note",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": credit_note.id,
        }

    def action_create_customer_invoice(self):
        """Create customer invoice for uncovered amounts."""
        self.ensure_one()
        if self.customer_total_amount <= 0:
            raise UserError("No customer amount to invoice.")

        if self.customer_invoice_id:
            raise UserError("A customer invoice already exists for this claim.")

        # Get customer from maintenance order
        customer = self.maintenance_order_id.customer_id
        if not customer:
            raise UserError("No customer defined on the work order.")

        invoice_lines = []

        if self.customer_parts_amount > 0:
            invoice_lines.append(
                (
                    0,
                    0,
                    {
                        "name": f"Parts (not covered) - {self.asset_id.name}",
                        "quantity": 1,
                        "price_unit": self.customer_parts_amount,
                    },
                )
            )

        if self.customer_labor_amount > 0:
            invoice_lines.append(
                (
                    0,
                    0,
                    {
                        "name": f"Labor (not covered) - {self.asset_id.name}",
                        "quantity": 1,
                        "price_unit": self.customer_labor_amount,
                    },
                )
            )

        if self.deductible_applied > 0:
            invoice_lines.append(
                (
                    0,
                    0,
                    {
                        "name": f"Deductible - {self.contract_id.display_name_custom}",
                        "quantity": 1,
                        "price_unit": self.deductible_applied,
                    },
                )
            )

        move_vals = {
            "move_type": "out_invoice",
            "partner_id": customer.id,
            "invoice_date": fields.Date.today(),
            "ref": self.maintenance_order_id.name,
            "invoice_line_ids": invoice_lines,
        }

        invoice = self.env["account.move"].create(move_vals)
        self.customer_invoice_id = invoice.id

        return {
            "type": "ir.actions.act_window",
            "name": "Customer Invoice",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": invoice.id,
        }

    def action_create_replacement_po(self):
        """Create PO to vendor for replacement parts."""
        self.ensure_one()
        if self.state not in ("approved", "partially_approved"):
            raise UserError("Claim must be approved first.")

        if self.purchase_order_id:
            raise UserError("A purchase order already exists for this claim.")

        parts_lines = self.line_ids.filtered(lambda ln: ln.line_type == "parts")
        if not parts_lines:
            raise UserError("No parts to order.")

        po_lines = []
        for line in parts_lines:
            product = line.product_id
            if not product:
                # Create or get a generic service product
                product = self._get_or_create_generic_product()

            po_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": line.description,
                        "product_qty": line.quantity,
                        "price_unit": 0.0,  # Warranty replacement
                    },
                )
            )

        po_vals = {
            "partner_id": self.contract_id.provider_id.id,
            "date_order": fields.Datetime.now(),
            "origin": f"Warranty Claim: {self.name}",
            "order_line": po_lines,
        }

        po = self.env["purchase.order"].create(po_vals)
        self.purchase_order_id = po.id

        return {
            "type": "ir.actions.act_window",
            "name": "Replacement Purchase Order",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": po.id,
        }

    def _get_or_create_generic_product(self):
        """Get or create a generic product for warranty parts."""
        product = self.env["product.product"].search(
            [("default_code", "=", "WARRANTY-PART")], limit=1
        )
        if not product:
            product = self.env["product.product"].create(
                {
                    "name": "Warranty Replacement Part",
                    "default_code": "WARRANTY-PART",
                    "type": "consu",
                    "purchase_ok": True,
                    "sale_ok": False,
                }
            )
        return product

    def action_mark_paid(self):
        """Mark claim as settled."""
        self.write({"state": "paid"})

    @api.model
    def _cron_claim_followup(self):
        """Cron job to remind about pending claims."""
        # Find claims submitted more than 7 days ago without response
        from datetime import timedelta

        cutoff_date = fields.Datetime.now() - timedelta(days=7)

        pending_claims = self.search(
            [
                ("state", "in", ("submitted", "under_review")),
                ("create_date", "<", cutoff_date),
            ]
        )

        for claim in pending_claims:
            claim.message_post(
                body=f"Reminder: Warranty claim {claim.name} is still pending "
                f"response from {claim.contract_id.provider_id.name}. "
                f"Please follow up.",
                subject=f"Claim Follow-up: {claim.name}",
                message_type="notification",
            )


class AssetzWarrantyClaimLine(models.Model):
    """Model for claim line items (parts or labor)."""

    _name = "assetz.warranty.claim.line"
    _description = "Warranty Claim Line"
    _order = "sequence, id"

    claim_id = fields.Many2one(
        comodel_name="assetz.warranty.claim",
        string="Claim",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)

    line_type = fields.Selection(
        selection=[
            ("parts", "Parts/Materials"),
            ("labor", "Labor"),
        ],
        string="Type",
        required=True,
        default="parts",
    )

    # For parts
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
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
        string="Total Amount",
        compute="_compute_amount",
        store=True,
        currency_field="currency_id",
    )

    # For labor
    hours = fields.Float(
        string="Hours",
    )
    hourly_rate = fields.Monetary(
        string="Hourly Rate",
        currency_field="currency_id",
    )

    # Coverage status (computed)
    is_covered = fields.Boolean(
        string="Covered",
        compute="_compute_coverage",
    )
    coverage_percent = fields.Float(
        string="Coverage %",
        compute="_compute_coverage",
    )

    currency_id = fields.Many2one(
        related="claim_id.currency_id",
        string="Currency",
    )

    notes = fields.Text(string="Notes")

    @api.depends("line_type", "quantity", "unit_cost", "hours", "hourly_rate")
    def _compute_amount(self):
        """Calculate line amount based on type."""
        for line in self:
            if line.line_type == "parts":
                line.amount = line.quantity * line.unit_cost
            else:  # labor
                line.amount = line.hours * line.hourly_rate

    @api.depends(
        "claim_id.contract_id",
        "claim_id.asset_id",
        "line_type",
        "amount",
    )
    def _compute_coverage(self):
        """Check if line is covered under contract."""
        for line in self:
            if not line.claim_id.contract_id or not line.claim_id.asset_id:
                line.is_covered = False
                line.coverage_percent = 0.0
                continue

            coverage = line.claim_id.contract_id.check_coverage(
                line.claim_id.asset_id,
                line.line_type,
                line.amount,
            )
            line.is_covered = coverage["is_covered"]
            line.coverage_percent = coverage["coverage_percent"]

    @api.onchange("line_type")
    def _onchange_line_type(self):
        """Clear irrelevant fields when line type changes."""
        if self.line_type == "parts":
            self.hours = 0.0
            self.hourly_rate = 0.0
        else:
            self.quantity = 0.0
            self.unit_cost = 0.0
            self.product_id = False
