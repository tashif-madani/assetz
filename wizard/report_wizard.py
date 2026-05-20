import io
import base64
from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    import xlsxwriter
    HAS_XLSXWRITER = True
except ImportError:
    HAS_XLSXWRITER = False


class AssetReportWizard(models.TransientModel):
    """Wizard for generating asset reports with filters."""

    _name = "assetz.report.wizard"
    _description = "Asset Report Wizard"

    report_type = fields.Selection(
        selection=[
            ("asset_summary", "Asset Summary Report"),
            ("asset_valuation", "Asset Valuation Report"),
            ("issued_assets", "Issued Assets Report"),
            ("warranty_status", "Warranty Status Report"),
            ("eol_report", "End of Life Report"),
            ("maintenance_report", "Maintenance Cost Report"),
            ("issue_order_report", "Issue Order Report"),
        ],
        string="Report Type",
        required=True,
        default="asset_summary",
    )

    date_from = fields.Date(
        string="Date From",
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="Date To",
        default=lambda self: date.today(),
    )

    category_ids = fields.Many2many(
        comodel_name="assetz.category",
        string="Categories",
        help="Leave empty to include all categories",
    )
    location_ids = fields.Many2many(
        comodel_name="assetz.location",
        string="Locations",
        help="Leave empty to include all locations",
    )

    state_filter = fields.Selection(
        selection=[
            ("all", "All States"),
            ("active", "Active Only"),
            ("maintenance", "Under Maintenance"),
            ("retired", "Retired"),
        ],
        string="Asset State",
        default="all",
    )

    issue_state_filter = fields.Selection(
        selection=[
            ("all", "All"),
            ("available", "Available"),
            ("issued", "Issued"),
            ("reserved", "Reserved"),
        ],
        string="Issue State",
        default="all",
    )

    output_format = fields.Selection(
        selection=[
            ("screen", "View on Screen"),
            ("excel", "Export to Excel"),
            ("pdf", "Export to PDF"),
        ],
        string="Output Format",
        required=True,
        default="screen",
    )

    # Output file
    excel_file = fields.Binary(string="Excel File", readonly=True)
    excel_filename = fields.Char(string="Filename", readonly=True)

    def _get_domain(self):
        """Build domain based on filters."""
        domain = []

        if self.category_ids:
            domain.append(("category_id", "in", self.category_ids.ids))

        if self.location_ids:
            domain.append(("location_id", "in", self.location_ids.ids))

        if self.state_filter != "all":
            domain.append(("state", "=", self.state_filter))

        if self.issue_state_filter != "all":
            domain.append(("issue_state", "=", self.issue_state_filter))

        return domain

    def _get_issue_order_domain(self):
        """Build domain for issue order reports."""
        domain = []

        if self.date_from:
            domain.append(("issue_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("issue_date", "<=", self.date_to))

        return domain

    def _get_maintenance_domain(self):
        """Build domain for maintenance reports."""
        domain = [("assetz_asset_id", "!=", False)]

        if self.date_from:
            domain.append(("schedule_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("schedule_date", "<=", self.date_to))

        return domain

    def action_generate_report(self):
        """Generate the selected report."""
        self.ensure_one()

        if self.output_format == "excel":
            return self._generate_excel_report()
        elif self.output_format == "pdf":
            return self._generate_pdf_report()
        else:
            return self._show_report_on_screen()

    def _show_report_on_screen(self):
        """Open the report in list/pivot view."""
        self.ensure_one()

        report_actions = {
            "asset_summary": "assetz.assetz_asset_by_category_action",
            "asset_valuation": "assetz.assetz_asset_valuation_report_action",
            "issued_assets": "assetz.assetz_asset_issued_report_action",
            "warranty_status": "assetz.assetz_asset_warranty_report_action",
            "eol_report": "assetz.assetz_asset_eol_report_action",
            "maintenance_report": "assetz.assetz_maintenance_report_action",
            "issue_order_report": "assetz.assetz_issue_order_report_action",
        }

        action_ref = report_actions.get(self.report_type)
        if not action_ref:
            raise UserError("Report type not configured.")

        action = self.env["ir.actions.act_window"]._for_xml_id(action_ref)

        # Apply additional domain from filters
        base_domain = action.get("domain") or []
        if isinstance(base_domain, str):
            base_domain = eval(base_domain)
        if not isinstance(base_domain, list):
            base_domain = []

        if self.report_type in ("asset_summary", "asset_valuation", "issued_assets", "warranty_status", "eol_report"):
            additional_domain = self._get_domain()
        elif self.report_type == "issue_order_report":
            additional_domain = self._get_issue_order_domain()
        elif self.report_type == "maintenance_report":
            additional_domain = self._get_maintenance_domain()
        else:
            additional_domain = []

        action["domain"] = base_domain + additional_domain
        return action

    def _generate_excel_report(self):
        """Generate Excel report."""
        if not HAS_XLSXWRITER:
            raise UserError("xlsxwriter library is required for Excel export. Install with: pip install xlsxwriter")

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})

        # Styles
        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#4472C4",
            "font_color": "white",
            "border": 1,
            "align": "center",
        })
        cell_format = workbook.add_format({"border": 1})
        money_format = workbook.add_format({"border": 1, "num_format": "#,##0.00"})
        date_format = workbook.add_format({"border": 1, "num_format": "yyyy-mm-dd"})
        title_format = workbook.add_format({
            "bold": True,
            "font_size": 14,
            "align": "center",
        })

        if self.report_type == "asset_summary":
            self._write_asset_summary_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "asset_valuation":
            self._write_asset_valuation_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "issued_assets":
            self._write_issued_assets_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "warranty_status":
            self._write_warranty_status_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "eol_report":
            self._write_eol_report_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "issue_order_report":
            self._write_issue_order_excel(workbook, header_format, cell_format, money_format, date_format, title_format)
        elif self.report_type == "maintenance_report":
            self._write_maintenance_report_excel(workbook, header_format, cell_format, money_format, date_format, title_format)

        workbook.close()
        output.seek(0)

        report_names = {
            "asset_summary": "Asset_Summary",
            "asset_valuation": "Asset_Valuation",
            "issued_assets": "Issued_Assets",
            "warranty_status": "Warranty_Status",
            "eol_report": "EOL_Report",
            "issue_order_report": "Issue_Order_Report",
            "maintenance_report": "Maintenance_Report",
        }

        filename = f"{report_names.get(self.report_type, 'Report')}_{date.today().strftime('%Y%m%d')}.xlsx"

        self.write({
            "excel_file": base64.b64encode(output.read()),
            "excel_filename": filename,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self._name}/{self.id}/excel_file/{filename}?download=true",
            "target": "self",
        }

    def _write_asset_summary_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write asset summary report to Excel."""
        sheet = workbook.add_worksheet("Asset Summary")
        domain = self._get_domain()
        assets = self.env["assetz.asset"].search(domain)

        # Title
        sheet.merge_range("A1:J1", "Asset Summary Report", title_format)
        sheet.write("A2", f"Generated: {date.today()}")

        # Headers
        headers = ["Code", "Name", "Category", "Location", "Assigned To", "Status", "Issue Status", "Acquisition Date", "Acquisition Cost", "Serial Number"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        # Data
        row = 4
        total_cost = 0
        for asset in assets:
            sheet.write(row, 0, asset.code or "", cell_format)
            sheet.write(row, 1, asset.name or "", cell_format)
            sheet.write(row, 2, asset.category_id.name if asset.category_id else "", cell_format)
            sheet.write(row, 3, asset.location_id.name if asset.location_id else "", cell_format)
            sheet.write(row, 4, asset.assigned_to_id.name if asset.assigned_to_id else "", cell_format)
            sheet.write(row, 5, dict(asset._fields["state"].selection).get(asset.state, ""), cell_format)
            sheet.write(row, 6, dict(asset._fields["issue_state"].selection).get(asset.issue_state, ""), cell_format)
            sheet.write(row, 7, str(asset.acquisition_date) if asset.acquisition_date else "", date_format)
            sheet.write(row, 8, asset.acquisition_cost or 0, money_format)
            sheet.write(row, 9, asset.serial_number or "", cell_format)
            total_cost += asset.acquisition_cost or 0
            row += 1

        # Summary
        sheet.write(row + 1, 7, "Total:", header_format)
        sheet.write(row + 1, 8, total_cost, money_format)

    def _write_asset_valuation_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write asset valuation report to Excel."""
        sheet = workbook.add_worksheet("Asset Valuation")
        domain = self._get_domain()
        assets = self.env["assetz.asset"].search(domain)

        sheet.merge_range("A1:H1", "Asset Valuation Report", title_format)
        sheet.write("A2", f"Generated: {date.today()}")

        headers = ["Code", "Name", "Category", "Location", "Acquisition Date", "Acquisition Cost", "Useful Life (Years)", "Salvage Value"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        total_cost = 0
        total_salvage = 0
        for asset in assets:
            sheet.write(row, 0, asset.code or "", cell_format)
            sheet.write(row, 1, asset.name or "", cell_format)
            sheet.write(row, 2, asset.category_id.name if asset.category_id else "", cell_format)
            sheet.write(row, 3, asset.location_id.name if asset.location_id else "", cell_format)
            sheet.write(row, 4, str(asset.acquisition_date) if asset.acquisition_date else "", date_format)
            sheet.write(row, 5, asset.acquisition_cost or 0, money_format)
            sheet.write(row, 6, asset.useful_life_years or 0, cell_format)
            sheet.write(row, 7, asset.salvage_value or 0, money_format)
            total_cost += asset.acquisition_cost or 0
            total_salvage += asset.salvage_value or 0
            row += 1

        sheet.write(row + 1, 4, "Totals:", header_format)
        sheet.write(row + 1, 5, total_cost, money_format)
        sheet.write(row + 1, 7, total_salvage, money_format)

    def _write_issued_assets_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write issued assets report to Excel."""
        sheet = workbook.add_worksheet("Issued Assets")
        domain = self._get_domain() + [("issue_state", "=", "issued")]
        assets = self.env["assetz.asset"].search(domain)

        sheet.merge_range("A1:H1", "Issued Assets Report", title_format)
        sheet.write("A2", f"Generated: {date.today()}")

        headers = ["Code", "Name", "Category", "Holder Type", "Current Holder", "Issue Date", "Expected Return", "Location"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        for asset in assets:
            sheet.write(row, 0, asset.code or "", cell_format)
            sheet.write(row, 1, asset.name or "", cell_format)
            sheet.write(row, 2, asset.category_id.name if asset.category_id else "", cell_format)
            sheet.write(row, 3, dict(asset._fields["current_holder_type"].selection).get(asset.current_holder_type, "") if asset.current_holder_type else "", cell_format)
            sheet.write(row, 4, asset.current_holder_display or "", cell_format)
            sheet.write(row, 5, str(asset.issue_date) if asset.issue_date else "", date_format)
            sheet.write(row, 6, str(asset.expected_return_date) if asset.expected_return_date else "", date_format)
            sheet.write(row, 7, asset.location_id.name if asset.location_id else "", cell_format)
            row += 1

        sheet.write(row + 1, 0, f"Total Issued Assets: {len(assets)}", header_format)

    def _write_warranty_status_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write warranty status report to Excel."""
        sheet = workbook.add_worksheet("Warranty Status")
        domain = self._get_domain() + [("state", "in", ["active", "maintenance"])]
        assets = self.env["assetz.asset"].search(domain)

        sheet.merge_range("A1:H1", "Warranty Status Report", title_format)
        sheet.write("A2", f"Generated: {date.today()}")

        headers = ["Code", "Name", "Category", "Manufacturer", "Acquisition Date", "Warranty End Date", "Days Left", "Status"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        for asset in assets:
            sheet.write(row, 0, asset.code or "", cell_format)
            sheet.write(row, 1, asset.name or "", cell_format)
            sheet.write(row, 2, asset.category_id.name if asset.category_id else "", cell_format)
            sheet.write(row, 3, asset.manufacturer or "", cell_format)
            sheet.write(row, 4, str(asset.acquisition_date) if asset.acquisition_date else "", date_format)
            sheet.write(row, 5, str(asset.warranty_end_date) if asset.warranty_end_date else "", date_format)
            sheet.write(row, 6, asset.warranty_days_remaining or 0, cell_format)
            sheet.write(row, 7, dict(asset._fields["warranty_status"].selection).get(asset.warranty_status, ""), cell_format)
            row += 1

    def _write_eol_report_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write EOL report to Excel."""
        sheet = workbook.add_worksheet("EOL Report")
        domain = self._get_domain() + [("eol_enabled", "=", True), ("eol_date", "!=", False)]
        assets = self.env["assetz.asset"].search(domain)

        sheet.merge_range("A1:I1", "End of Life Report", title_format)
        sheet.write("A2", f"Generated: {date.today()}")

        headers = ["Code", "Name", "Category", "Location", "Acquisition Date", "Age (Days)", "EOL Date", "Days Until EOL", "EOL Reason"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        for asset in assets:
            sheet.write(row, 0, asset.code or "", cell_format)
            sheet.write(row, 1, asset.name or "", cell_format)
            sheet.write(row, 2, asset.category_id.name if asset.category_id else "", cell_format)
            sheet.write(row, 3, asset.location_id.name if asset.location_id else "", cell_format)
            sheet.write(row, 4, str(asset.acquisition_date) if asset.acquisition_date else "", date_format)
            sheet.write(row, 5, asset.age_days or 0, cell_format)
            sheet.write(row, 6, str(asset.eol_date) if asset.eol_date else "", date_format)
            sheet.write(row, 7, asset.days_until_eol or 0, cell_format)
            sheet.write(row, 8, dict(asset._fields["eol_reason"].selection).get(asset.eol_reason, "") if asset.eol_reason else "", cell_format)
            row += 1

    def _write_issue_order_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write issue order report to Excel."""
        sheet = workbook.add_worksheet("Issue Orders")
        domain = self._get_issue_order_domain()
        orders = self.env["assetz.issue.order"].search(domain)

        sheet.merge_range("A1:H1", "Issue Order Report", title_format)
        sheet.write("A2", f"Period: {self.date_from} to {self.date_to}")

        headers = ["Reference", "Recipient Type", "Recipient", "Issue Type", "Issue Date", "Expected Return", "Asset Count", "Status"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        total_assets = 0
        for order in orders:
            sheet.write(row, 0, order.name or "", cell_format)
            sheet.write(row, 1, dict(order._fields["recipient_type"].selection).get(order.recipient_type, ""), cell_format)
            sheet.write(row, 2, order.recipient_display or "", cell_format)
            sheet.write(row, 3, dict(order._fields["issue_type"].selection).get(order.issue_type, ""), cell_format)
            sheet.write(row, 4, str(order.issue_date) if order.issue_date else "", date_format)
            sheet.write(row, 5, str(order.expected_return_date) if order.expected_return_date else "", date_format)
            sheet.write(row, 6, order.asset_count or 0, cell_format)
            sheet.write(row, 7, dict(order._fields["state"].selection).get(order.state, ""), cell_format)
            total_assets += order.asset_count or 0
            row += 1

        sheet.write(row + 1, 5, "Total Assets:", header_format)
        sheet.write(row + 1, 6, total_assets, cell_format)

    def _write_maintenance_report_excel(self, workbook, header_format, cell_format, money_format, date_format, title_format):
        """Write maintenance report to Excel."""
        sheet = workbook.add_worksheet("Maintenance Report")
        domain = self._get_maintenance_domain()
        requests = self.env["maintenance.request"].search(domain)

        sheet.merge_range("A1:I1", "Maintenance Cost Report", title_format)
        sheet.write("A2", f"Period: {self.date_from} to {self.date_to}")

        headers = ["Reference", "Asset", "Request Date", "Schedule Date", "Type", "Warranty Status", "Parts Cost", "Labor Cost", "Total Cost"]
        for col, header in enumerate(headers):
            sheet.write(3, col, header, header_format)
            sheet.set_column(col, col, 15)

        row = 4
        total_parts = 0
        total_labor = 0
        total_cost = 0
        for req in requests:
            sheet.write(row, 0, req.name or "", cell_format)
            sheet.write(row, 1, req.assetz_asset_id.name if req.assetz_asset_id else "", cell_format)
            sheet.write(row, 2, str(req.request_date) if req.request_date else "", date_format)
            sheet.write(row, 3, str(req.schedule_date) if req.schedule_date else "", date_format)
            sheet.write(row, 4, dict(req._fields["maintenance_type"].selection).get(req.maintenance_type, "") if hasattr(req, "maintenance_type") else "", cell_format)
            sheet.write(row, 5, dict(req._fields["warranty_status"].selection).get(req.warranty_status, "") if hasattr(req, "warranty_status") else "", cell_format)
            sheet.write(row, 6, req.parts_cost if hasattr(req, "parts_cost") else 0, money_format)
            sheet.write(row, 7, req.labor_cost if hasattr(req, "labor_cost") else 0, money_format)
            sheet.write(row, 8, req.total_cost if hasattr(req, "total_cost") else 0, money_format)
            total_parts += req.parts_cost if hasattr(req, "parts_cost") else 0
            total_labor += req.labor_cost if hasattr(req, "labor_cost") else 0
            total_cost += req.total_cost if hasattr(req, "total_cost") else 0
            row += 1

        sheet.write(row + 1, 5, "Totals:", header_format)
        sheet.write(row + 1, 6, total_parts, money_format)
        sheet.write(row + 1, 7, total_labor, money_format)
        sheet.write(row + 1, 8, total_cost, money_format)

    def _generate_pdf_report(self):
        """Generate PDF report using QWeb."""
        self.ensure_one()

        report_refs = {
            "asset_summary": "assetz.action_report_asset_summary",
            "asset_valuation": "assetz.action_report_asset_valuation",
            "issued_assets": "assetz.action_report_issued_assets",
            "warranty_status": "assetz.action_report_warranty_status",
            "eol_report": "assetz.action_report_eol",
            "issue_order_report": "assetz.action_report_issue_orders",
            "maintenance_report": "assetz.action_report_maintenance",
        }

        report_ref = report_refs.get(self.report_type)
        if not report_ref:
            raise UserError("PDF report not available for this report type.")

        return self.env.ref(report_ref).report_action(self)
