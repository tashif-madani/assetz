from odoo import api, fields, models
from odoo.exceptions import UserError


class WOCloseWizard(models.TransientModel):
    """Wizard for closing work orders with billing determination."""

    _name = "assetz.wo.close.wizard"
    _description = "Work Order Close Wizard"

    maintenance_order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Work Order",
        required=True,
    )
    asset_id = fields.Many2one(
        related="maintenance_order_id.asset_id",
        string="Asset",
    )

    # Cost Summary (from work order)
    total_parts_cost = fields.Monetary(
        related="maintenance_order_id.parts_cost",
        string="Total Parts Cost",
    )
    total_labor_cost = fields.Monetary(
        related="maintenance_order_id.labor_cost",
        string="Total Labor Cost",
    )
    total_cost = fields.Monetary(
        related="maintenance_order_id.total_cost",
        string="Total Cost",
    )
    currency_id = fields.Many2one(
        related="maintenance_order_id.currency_id",
    )

    # Contract Selection
    has_active_contract = fields.Boolean(
        related="maintenance_order_id.has_active_contract",
    )
    contract_id = fields.Many2one(
        comodel_name="assetz.service.contract",
        string="Apply Contract",
        domain="[('id', 'in', available_contract_ids)]",
    )
    available_contract_ids = fields.Many2many(
        comodel_name="assetz.service.contract",
        string="Available Contracts",
        compute="_compute_available_contracts",
    )

    # Coverage Preview
    parts_covered_percent = fields.Float(
        string="Parts Coverage %",
        compute="_compute_coverage_preview",
    )
    labor_covered_percent = fields.Float(
        string="Labor Coverage %",
        compute="_compute_coverage_preview",
    )
    parts_covered_amount = fields.Monetary(
        string="Parts Covered",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )
    labor_covered_amount = fields.Monetary(
        string="Labor Covered",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )
    deductible_amount = fields.Monetary(
        string="Deductible",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )
    total_covered = fields.Monetary(
        string="Total Covered",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )

    # Customer Responsibility
    customer_parts_amount = fields.Monetary(
        string="Customer Parts",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )
    customer_labor_amount = fields.Monetary(
        string="Customer Labor",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )
    customer_total = fields.Monetary(
        string="Customer Total",
        compute="_compute_coverage_preview",
        currency_field="currency_id",
    )

    # Billing Decision
    billing_outcome = fields.Selection(
        selection=[
            ("claim_only", "Warranty Claim Only"),
            ("bill_customer_only", "Bill Customer Only"),
            ("claim_and_bill", "Warranty Claim + Bill Customer"),
            ("internal_cost", "Internal Cost Center"),
            ("no_charge", "No Charge"),
        ],
        string="Billing Outcome",
        required=True,
        default="claim_and_bill",
    )

    # Actions to take
    create_warranty_claim = fields.Boolean(
        string="Create Warranty Claim",
        default=True,
    )
    create_customer_invoice = fields.Boolean(
        string="Create Customer Invoice",
        default=True,
    )
    customer_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        related="maintenance_order_id.partner_id",
    )

    # Internal cost allocation
    internal_cost_center = fields.Char(
        string="Cost Center",
    )

    notes = fields.Text(string="Notes")

    @api.depends("maintenance_order_id", "maintenance_order_id.asset_id")
    def _compute_available_contracts(self):
        """Find available contracts for the asset."""
        for wizard in self:
            if not wizard.maintenance_order_id or not wizard.asset_id:
                wizard.available_contract_ids = False
                continue

            asset = wizard.asset_id
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
            wizard.available_contract_ids = contracts

    @api.model
    def default_get(self, fields_list):
        """Set default contract from maintenance order."""
        res = super().default_get(fields_list)
        if "maintenance_order_id" in res:
            mo = self.env["assetz.maintenance.order"].browse(
                res["maintenance_order_id"]
            )
            if mo.contract_id:
                res["contract_id"] = mo.contract_id.id
        return res

    @api.depends("contract_id", "total_parts_cost", "total_labor_cost", "asset_id")
    def _compute_coverage_preview(self):
        """Preview coverage amounts based on selected contract."""
        for wizard in self:
            if not wizard.contract_id or not wizard.asset_id:
                wizard.parts_covered_percent = 0.0
                wizard.labor_covered_percent = 0.0
                wizard.parts_covered_amount = 0.0
                wizard.labor_covered_amount = 0.0
                wizard.deductible_amount = 0.0
                wizard.total_covered = 0.0
                wizard.customer_parts_amount = wizard.total_parts_cost
                wizard.customer_labor_amount = wizard.total_labor_cost
                wizard.customer_total = wizard.total_cost
                continue

            contract = wizard.contract_id

            # Parts coverage
            parts_result = contract.check_coverage(
                wizard.asset_id, "parts", wizard.total_parts_cost
            )
            wizard.parts_covered_percent = parts_result["coverage_percent"]
            wizard.parts_covered_amount = (
                parts_result["max_claimable"] if parts_result["is_covered"] else 0.0
            )

            # Labor coverage
            labor_result = contract.check_coverage(
                wizard.asset_id, "labor", wizard.total_labor_cost
            )
            wizard.labor_covered_percent = labor_result["coverage_percent"]
            wizard.labor_covered_amount = (
                labor_result["max_claimable"] if labor_result["is_covered"] else 0.0
            )

            # Deductible
            total_claimable = (
                wizard.parts_covered_amount + wizard.labor_covered_amount
            )
            wizard.deductible_amount = min(
                contract.deductible_amount, total_claimable
            )

            # Total covered
            wizard.total_covered = total_claimable - wizard.deductible_amount

            # Customer responsibility
            wizard.customer_parts_amount = (
                wizard.total_parts_cost - wizard.parts_covered_amount
            )
            wizard.customer_labor_amount = (
                wizard.total_labor_cost - wizard.labor_covered_amount
            )
            wizard.customer_total = (
                wizard.customer_parts_amount
                + wizard.customer_labor_amount
                + wizard.deductible_amount
            )

    @api.onchange("contract_id")
    def _onchange_contract_id(self):
        """Update billing outcome based on coverage."""
        if not self.contract_id:
            self.billing_outcome = "bill_customer_only"
            self.create_warranty_claim = False
            self.create_customer_invoice = True
        elif self.total_covered > 0 and self.customer_total > 0:
            self.billing_outcome = "claim_and_bill"
            self.create_warranty_claim = True
            self.create_customer_invoice = True
        elif self.total_covered > 0:
            self.billing_outcome = "claim_only"
            self.create_warranty_claim = True
            self.create_customer_invoice = False
        else:
            self.billing_outcome = "bill_customer_only"
            self.create_warranty_claim = False
            self.create_customer_invoice = True

    @api.onchange("billing_outcome")
    def _onchange_billing_outcome(self):
        """Update flags based on billing outcome."""
        if self.billing_outcome == "claim_only":
            self.create_warranty_claim = True
            self.create_customer_invoice = False
        elif self.billing_outcome == "bill_customer_only":
            self.create_warranty_claim = False
            self.create_customer_invoice = True
        elif self.billing_outcome == "claim_and_bill":
            self.create_warranty_claim = True
            self.create_customer_invoice = True
        elif self.billing_outcome == "internal_cost":
            self.create_warranty_claim = False
            self.create_customer_invoice = False
        elif self.billing_outcome == "no_charge":
            self.create_warranty_claim = False
            self.create_customer_invoice = False

    def action_close_work_order(self):
        """Close the work order and execute billing decisions."""
        self.ensure_one()
        wo = self.maintenance_order_id

        # Create warranty claim if needed
        claim = None
        if (
            self.create_warranty_claim
            and self.contract_id
            and self.total_covered > 0
        ):
            claim = self._create_warranty_claim()

        # Create customer invoice if needed
        invoice = None
        if (
            self.create_customer_invoice
            and self.customer_total > 0
            and self.customer_id
        ):
            invoice = self._create_customer_invoice()

        # Update work order billing status
        if self.billing_outcome == "claim_only":
            wo.billing_status = "covered"
        elif self.billing_outcome == "claim_and_bill":
            wo.billing_status = "partially_covered"
        elif self.billing_outcome == "bill_customer_only":
            wo.billing_status = "bill_customer"
        elif self.billing_outcome == "internal_cost":
            wo.billing_status = "internal"

        # Complete the maintenance order
        if wo.state == "in_progress":
            wo.action_complete()

        # Return appropriate action
        if claim:
            return {
                "type": "ir.actions.act_window",
                "name": "Warranty Claim Created",
                "res_model": "assetz.warranty.claim",
                "view_mode": "form",
                "res_id": claim.id,
            }
        elif invoice:
            return {
                "type": "ir.actions.act_window",
                "name": "Customer Invoice Created",
                "res_model": "account.move",
                "view_mode": "form",
                "res_id": invoice.id,
            }

        return {"type": "ir.actions.act_window_close"}

    def _create_warranty_claim(self):
        """Create warranty claim from work order."""
        wo = self.maintenance_order_id

        claim_vals = {
            "maintenance_order_id": wo.id,
            "contract_id": self.contract_id.id,
            "asset_id": self.asset_id.id,
            "description": f"Maintenance: {wo.name}\n{wo.description or ''}",
            "line_ids": [],
        }

        # Add parts lines
        for parts_line in wo.parts_line_ids:
            claim_vals["line_ids"].append(
                (
                    0,
                    0,
                    {
                        "line_type": "parts",
                        "product_id": parts_line.product_id.id
                        if parts_line.product_id
                        else False,
                        "description": parts_line.description,
                        "quantity": parts_line.quantity,
                        "unit_cost": parts_line.unit_cost,
                    },
                )
            )

        # Add labor lines
        for labor_line in wo.labor_line_ids:
            claim_vals["line_ids"].append(
                (
                    0,
                    0,
                    {
                        "line_type": "labor",
                        "description": labor_line.description,
                        "hours": labor_line.hours,
                        "hourly_rate": labor_line.hourly_rate,
                    },
                )
            )

        return self.env["assetz.warranty.claim"].create(claim_vals)

    def _create_customer_invoice(self):
        """Create customer invoice for uncovered amounts."""
        wo = self.maintenance_order_id

        invoice_lines = []

        if self.customer_parts_amount > 0:
            invoice_lines.append(
                (
                    0,
                    0,
                    {
                        "name": f"Parts - {self.asset_id.name} ({wo.name})",
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
                        "name": f"Labor - {self.asset_id.name} ({wo.name})",
                        "quantity": 1,
                        "price_unit": self.customer_labor_amount,
                    },
                )
            )

        if self.deductible_amount > 0:
            invoice_lines.append(
                (
                    0,
                    0,
                    {
                        "name": f"Deductible - {self.contract_id.display_name_custom}",
                        "quantity": 1,
                        "price_unit": self.deductible_amount,
                    },
                )
            )

        invoice_vals = {
            "move_type": "out_invoice",
            "partner_id": self.customer_id.id,
            "invoice_date": fields.Date.today(),
            "ref": wo.name,
            "invoice_line_ids": invoice_lines,
        }

        return self.env["account.move"].create(invoice_vals)
