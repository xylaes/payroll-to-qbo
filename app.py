import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import json
from datetime import datetime

class PayrollTransformer:
    """Handles the data transformation logic with security and accounting rules."""
    
    PII_COLUMNS = ['SSN', 'First Name', 'Last Name', 'Employee ID', 'Birth Date']
    
    CLASS_MAP = {
        'Connect': '01-ATL:Connect',
        'Design Build': '01-ATL:Design',
        'Enhancement': '01-ATL:Enhanc',
        'Maintenance': '01-ATL:Maint'
    }

    # Mapping wages to GL based on Division
    WAGE_REGULAR_GL_MAP = {
        'Design Build': '4.6.1',
        'Enhancement': '4.6.7',
        'Connect': '4.6.5',
        'Maintenance': '4.6.3'
    }
    
    WAGE_OVERTIME_GL_MAP = {
        'Design Build': '4.6.2',
        'Enhancement': '4.6.8',
        'Connect': '4.6.6',
        'Maintenance': '4.6.4'
    }

    def __init__(self, config_path="salaried_splits.json"):
        self.config_path = config_path

    @staticmethod
    def clean_data(df):
        """Immediately strip PII from the dataframe."""
        cols_to_drop = [c for c in PayrollTransformer.PII_COLUMNS if c in df.columns]
        return df.drop(columns=cols_to_drop)

    def load_splits(self):
        """Loads salaried splits from config file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_splits(self, splits):
        """Saves salaried splits to config file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(splits, f, indent=2)
        except Exception:
            pass

    def get_salaried_split(self, employee_num, dept_name):
        """Retrieves percentage split for salaried employee by employee number."""
        splits = self.load_splits()
        emp_key = str(employee_num) if employee_num is not None else ""
        if emp_key in splits:
            return splits[emp_key]
        
        # Fallback parsing based on department name
        dept_lower = str(dept_name).lower()
        if 'maintenance' in dept_lower and 'office - maintenance' in dept_lower:
            return {'01-ATL:Maint': 1.0}
        elif 'maint/enh' in dept_lower:
            return {'01-ATL:Maint': 0.5, '01-ATL:Enhanc': 0.5}
        elif 'all divisions' in dept_lower:
            return {'01-ATL:Design': 0.25, '01-ATL:Enhanc': 0.25, '01-ATL:Connect': 0.25, '01-ATL:Maint': 0.25}
        elif 'office - enh' in dept_lower:
            return {'01-ATL:Enhanc': 1.0}
        elif 'office - db' in dept_lower and 'db/enh/m' not in dept_lower:
            return {'01-ATL:Design': 1.0}
        elif 'db/enh/m' in dept_lower:
            return {'01-ATL:Design': 0.34, '01-ATL:Enhanc': 0.33, '01-ATL:Maint': 0.33}
        
        # Default fallback
        return {'01-ATL:Maint': 1.0}

    def map_department_to_class(self, dept_name):
        """Maps a department name to a QBO class."""
        dept_lower = str(dept_name).lower()
        if 'design' in dept_lower:
            return '01-ATL:Design'
        elif 'enhanc' in dept_lower:
            return '01-ATL:Enhanc'
        elif 'connect' in dept_lower:
            return '01-ATL:Connect'
        else:
            return '01-ATL:Maint'

    def get_hourly_split(self, row):
        """Computes split percentages for hourly employee based on direct wage distribution."""
        div_wages = {
            'Design Build': row.get('Wages-Regular-Design Build', 0),
            'Enhancement': row.get('Wages-Regular-Enhancement', 0),
            'Connect': row.get('Wages-Regular-Connect', 0),
            'Maintenance': row.get('Wages-Regular-Maintenance', 0)
        }
        # Zero out NaNs
        div_wages = {k: (0 if pd.isna(v) else v) for k, v in div_wages.items()}
        
        total_direct = sum(div_wages.values())
        if total_direct > 0:
            return {self.CLASS_MAP[k]: v / total_direct for k, v in div_wages.items() if v > 0}
        
        # Fallbacks
        div_name = row.get('Division Name', '')
        if div_name in self.CLASS_MAP:
            return {self.CLASS_MAP[div_name]: 1.0}
            
        class_name = self.map_department_to_class(row.get('Department Name', ''))
        return {class_name: 1.0}

    def extract_pay_date(self, df):
        """Extracts pay date from raw input rows or falls back to template date."""
        default_date = "2026-05-14"
        
        # Look for explicit date column headers
        date_keywords = ['check date', 'pay date', 'period end', 'payment date', 'date']
        ignore_keywords = ['hire', 'birth', 'rehire', 'termination']
        
        for col in df.columns:
            col_lower = col.lower()
            if any(k in col_lower for k in date_keywords) and not any(ik in col_lower for ik in ignore_keywords):
                non_null = df[col].dropna()
                if not non_null.empty:
                    try:
                        return pd.to_datetime(non_null.iloc[0]).strftime('%Y-%m-%d')
                    except Exception:
                        pass
        
        # Regex scan for date cells in first few rows
        import re
        date_pattern = re.compile(r'\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{1,2}-\d{1,2}')
        for col in df.columns:
            col_lower = col.lower()
            if any(ik in col_lower for ik in ignore_keywords):
                continue
            for val in df[col].dropna().head(5):
                if isinstance(val, str) and date_pattern.match(val):
                    try:
                        return pd.to_datetime(val).strftime('%Y-%m-%d')
                    except Exception:
                        pass
                        
        return default_date

    def distribute_amount(self, amount, splits):
        """Distributes an amount across splits, ensuring exact rounding matching."""
        if amount == 0 or pd.isna(amount):
            return {}
        
        distributed = {}
        remaining = amount
        keys = list(splits.keys())
        
        for k in keys[:-1]:
            val = round(amount * splits[k], 2)
            distributed[k] = val
            remaining -= val
            
        if keys:
            distributed[keys[-1]] = round(remaining, 2)
            
        return distributed

    def transform(self, input_file, payroll_fees=0.0):
        # 1. Load Data
        df = pd.read_csv(input_file)
        
        # 2. Extract Date
        pay_date = self.extract_pay_date(df)
        
        # 3. Security: Strip PII immediately
        df = self.clean_data(df)
        
        # Calculate overall splits from the entire payroll for manual fee allocation
        overall_class_wages = {c: 0.0 for c in self.CLASS_MAP.values()}
        for _, row in df.iterrows():
            emp_num = row.get('Employee Number')
            is_exempt = row.get('Overtime Status') == 'Exempt'
            dept_name = row.get('Department Name', '')
            
            if is_exempt:
                wages = row.get('Wages-Regular', 0)
                if pd.isna(wages): wages = 0
                other_nt = row.get('Wages-Other Non Taxable', 0) or row.get('Wages-Reimbursement - Non Taxable', 0)
                if pd.isna(other_nt): other_nt = 0
                wages += other_nt
                bonus_referral = row.get('Wages-Bonus - Referral', 0)
                if pd.isna(bonus_referral): bonus_referral = 0
                wages += bonus_referral
                
                splits = self.get_salaried_split(emp_num, dept_name)
                for qclass, pct in splits.items():
                    overall_class_wages[qclass] += wages * pct
            else:
                wages_by_div = {
                    'Design Build': row.get('Wages-Regular-Design Build', 0),
                    'Enhancement': row.get('Wages-Regular-Enhancement', 0),
                    'Connect': row.get('Wages-Regular-Connect', 0),
                    'Maintenance': row.get('Wages-Regular-Maintenance', 0)
                }
                wages_by_div = {k: (0 if pd.isna(v) else v) for k, v in wages_by_div.items()}
                wages_indirect = row.get('Wages-Regular-Indirect', 0)
                if pd.isna(wages_indirect): wages_indirect = 0
                wages_regular_generic = row.get('Wages-Regular', 0)
                if pd.isna(wages_regular_generic): wages_regular_generic = 0
                bonus_referral = row.get('Wages-Bonus - Referral', 0)
                if pd.isna(bonus_referral): bonus_referral = 0
                
                total_wages = sum(wages_by_div.values()) + wages_indirect + wages_regular_generic + bonus_referral
                
                splits = self.get_hourly_split(row)
                for qclass, pct in splits.items():
                    overall_class_wages[qclass] += total_wages * pct
                    
        total_overall_wages = sum(overall_class_wages.values())
        if total_overall_wages > 0:
            overall_splits = {k: v / total_overall_wages for k, v in overall_class_wages.items() if v > 0}
        else:
            overall_splits = {c: 0.25 for c in self.CLASS_MAP.values()}

        journal_rows = []
        
        def add_journal_row(gl_code, debit, credit, memo, qbo_class, notes=""):
            debit_val = round(debit, 2) if debit > 0 else 0.0
            credit_val = round(credit, 2) if credit > 0 else 0.0
            if debit_val == 0.0 and credit_val == 0.0:
                return
            journal_rows.append({
                'Date': pay_date,
                'GL Code': str(gl_code),
                'Debit': debit_val,
                'Credit': credit_val,
                'Memo': memo,
                'CLASS': qbo_class,
                'NOTES': notes
            })

        for _, row in df.iterrows():
            emp_num = row.get('Employee Number')
            is_exempt = row.get('Overtime Status') == 'Exempt'
            dept_name = row.get('Department Name', '')
            
            # Non-exempt maps by department designation for other columns
            dept_class = self.map_department_to_class(dept_name)
            
            # Determine splits
            if is_exempt:
                splits = self.get_salaried_split(emp_num, dept_name)
            else:
                splits = self.get_hourly_split(row)
            
            # Extract Child Support deduction to subtract from Wages to keep journal balanced
            child_support = row.get('Ded-Child Support', 0)
            if pd.isna(child_support): child_support = 0

            # ---------------- WAGES ----------------
            if is_exempt:
                wages = row.get('Wages-Regular', 0)
                if pd.isna(wages): wages = 0
                
                # Wages-Other Non Taxable or Wages-Reimbursement - Non Taxable for salaried matches regular wage GL
                other_nt = row.get('Wages-Other Non Taxable', 0) or row.get('Wages-Reimbursement - Non Taxable', 0)
                if pd.isna(other_nt): other_nt = 0
                wages += other_nt
                
                # Referral Bonus
                bonus_referral = row.get('Wages-Bonus - Referral', 0)
                if pd.isna(bonus_referral): bonus_referral = 0
                wages += bonus_referral
                
                net_wages = max(0.0, wages - child_support)
                dist_wages = self.distribute_amount(net_wages, splits)
                for qclass, val in dist_wages.items():
                    add_journal_row('70200', val, 0, 'Wages Payable:  Regular', qclass)
            else:
                # Hourly regular wage columns
                wages_by_div = {
                    'Design Build': row.get('Wages-Regular-Design Build', 0),
                    'Enhancement': row.get('Wages-Regular-Enhancement', 0),
                    'Connect': row.get('Wages-Regular-Connect', 0),
                    'Maintenance': row.get('Wages-Regular-Maintenance', 0)
                }
                wages_by_div = {k: (0 if pd.isna(v) else v) for k, v in wages_by_div.items()}
                
                wages_indirect = row.get('Wages-Regular-Indirect', 0)
                if pd.isna(wages_indirect): wages_indirect = 0
                
                wages_regular_generic = row.get('Wages-Regular', 0)
                if pd.isna(wages_regular_generic): wages_regular_generic = 0
                
                # Referral Bonus
                bonus_referral = row.get('Wages-Bonus - Referral', 0)
                if pd.isna(bonus_referral): bonus_referral = 0
                
                total_wages = sum(wages_by_div.values()) + wages_indirect + wages_regular_generic + bonus_referral
                net_wages = max(0.0, total_wages - child_support)
                
                # Distribute regular wages
                dist_wages = self.distribute_amount(net_wages, splits)
                for qclass, val in dist_wages.items():
                    # Match class to division for GL code
                    # (Find original division matching this class)
                    div_key = 'Maintenance'
                    for dk, cv in self.CLASS_MAP.items():
                        if cv == qclass:
                            div_key = dk
                            break
                    gl = self.WAGE_REGULAR_GL_MAP.get(div_key, '4.6.3')
                    add_journal_row(gl, val, 0, 'Wages Payable:  Regular', qclass)
                
                # Overtime
                ot_by_div = {
                    'Design Build': row.get('Wages-Overtime-Design Build', 0),
                    'Enhancement': row.get('Wages-Overtime-Enhancement', 0),
                    'Connect': row.get('Wages-Overtime-Connect', 0),
                    'Maintenance': row.get('Wages-Overtime-Maintenance', 0)
                }
                ot_by_div = {k: (0 if pd.isna(v) else v) for k, v in ot_by_div.items()}
                
                ot_indirect = row.get('Wages-Overtime-Indirect', 0)
                if pd.isna(ot_indirect): ot_indirect = 0
                
                ot_generic = row.get('Wages-Overtime', 0)
                if pd.isna(ot_generic): ot_generic = 0
                
                direct_ot_total = sum(ot_by_div.values())
                if direct_ot_total > 0 or ot_indirect > 0:
                    if direct_ot_total > 0:
                        ot_splits = {self.CLASS_MAP[k]: v / direct_ot_total for k, v in ot_by_div.items() if v > 0}
                    else:
                        ot_splits = splits
                    dist_ot_indirect = self.distribute_amount(ot_indirect, ot_splits)
                    for div_name, ot_val in ot_by_div.items():
                        qclass = self.CLASS_MAP[div_name]
                        val = ot_val + dist_ot_indirect.get(qclass, 0.0)
                        gl = self.WAGE_OVERTIME_GL_MAP.get(div_name, '4.6.4')
                        add_journal_row(gl, val, 0, 'Wages Payable:  Overtime', qclass)
                elif ot_generic > 0:
                    dist_ot = self.distribute_amount(ot_generic, splits)
                    for qclass, val in dist_ot.items():
                        div_key = 'Maintenance'
                        for dk, cv in self.CLASS_MAP.items():
                            if cv == qclass:
                                div_key = dk
                                break
                        gl = self.WAGE_OVERTIME_GL_MAP.get(div_key, '4.6.4')
                        add_journal_row(gl, val, 0, 'Wages Payable:  Overtime', qclass)

            # Wages-Cell Phone Reimbursement (Debit)
            cell_reimb = row.get('Wages-Cell Phone Reimbursement', 0)
            if pd.isna(cell_reimb): cell_reimb = 0
            if cell_reimb > 0:
                dist = self.distribute_amount(cell_reimb, splits if is_exempt else {dept_class: 1.0})
                for qclass, val in dist.items():
                    add_journal_row('7.16', val, 0, 'Employee Ded (Liability):  Cell Phone', qclass)

            # ---------------- EMPLOYEE DEDUCTIONS (Credits) ----------------
            deductions_map = {
                'Ded-Cell Phone-Uncollected': ('7.16', 'Employee Ded (Liability):  Cell Phone'),
                'Ded-Dental-Uncollected': ('20570', 'Employee Ded (Liability):  Dental High'),
                'Ded-HSA Family (Medical $6350)-Uncollected': ('20500', 'Employee Ded (Liability):  HSA Family (Medical $6350)'),
                'Ded-HSA Individual (Medical $5000)-Uncollected': ('20500', 'Employee Ded (Liability):  HSA Individual (Medical $5000)'),
                'Ded-HSA Individual (Medical $6350)-Uncollected': ('20500', 'Employee Ded (Liability):  HSA Individual (Medical $6350)'),
                'Ded-Medical-Uncollected': ('20550', 'Employee Ded (Liability):  $5000 Medical HSA Plan'),
                'Ded-Simple IRA Roth-Uncollected': ('20700', 'Employee Ded (Liability):  Simple IRA Roth'),
                'Ded-Simple IRA-Uncollected': ('20700', 'Employee Ded (Liability):  Simple IRA'),
                'Ded-Vision-Uncollected': ('20575', 'Employee Ded (Liability):  Vision Plan'),
                'Ded-Voluntary Term Life & AD&D-Uncollected': ('20560', 'Employee Ded (Liability):  Voluntary Term Life & AD&D'),
                'Ded-Uniform-Uncollected': ('10.05', 'Employee Ded (Liability):  Uniform'),
                'Ded-Materials purchase-Uncollected': ('10.05', 'Employee Ded (Liability):  Materials purchase')
            }
            
            for col, (gl, memo) in deductions_map.items():
                val = row.get(col, 0)
                if pd.isna(val): val = 0
                if val > 0:
                    dist = self.distribute_amount(val, splits if is_exempt else {dept_class: 1.0})
                    for qclass, amt in dist.items():
                        add_journal_row(gl, 0, amt, memo, qclass)

            # ---------------- EMPLOYER DEDUCTIONS (ER Matches) ----------------
            # Simple IRA Match
            ira_er = row.get('Ded-Total-Simple IRA-ER-Uncollected', 0)
            if pd.isna(ira_er): ira_er = 0
            if ira_er > 0:
                dist = self.distribute_amount(ira_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('5.01', amt, 0, 'Employer Ded (Expense):  Simple IRA', qclass)
                    add_journal_row('5.01', 0, amt, 'Employer Ded (Liability):  Simple IRA', qclass)

            # Group Term Life Match
            life_er = row.get('Ded-Total-Group Term Life & AD&D-ER-Uncollected', 0)
            if pd.isna(life_er): life_er = 0
            if life_er > 0:
                dist = self.distribute_amount(life_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('9.01', amt, 0, 'Employer Ded (Expense):  Group Term Life & AD&D', qclass)
                    add_journal_row('20560', 0, amt, 'Employer Ded (Liability):  Group Term Life & AD&D', qclass)

            # Medical HSA Match
            med_er = row.get('Ded-Total-Medical-ER-Uncollected', 0)
            if pd.isna(med_er): med_er = 0
            if med_er > 0:
                dist = self.distribute_amount(med_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('9.012', amt, 0, 'Employer Ded (Expense):  $5000 Medical HSA Plan', qclass)
                    add_journal_row('20550', 0, amt, 'Employer Ded (Liability):  $5000 Medical HSA Plan', qclass)

            # HSA Match (Individual $5000)
            hsa5k_er = row.get('Ded-Total-HSA Individual (Medical $5000)-ER-Uncollected', 0)
            if pd.isna(hsa5k_er): hsa5k_er = 0
            if hsa5k_er > 0:
                dist = self.distribute_amount(hsa5k_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('70212', amt, 0, 'Employer Ded (Expense):  HSA Individual (Medical $5000)', qclass)
                    add_journal_row('70212', 0, amt, 'Employer Ded (Liability):  HSA Individual (Medical $5000)', qclass)

            # HSA Match (Family $6350)
            hsa_fam = row.get('Ded-Total-HSA Family (Medical $6350)-ER-Uncollected', 0)
            if pd.isna(hsa_fam): hsa_fam = 0
            if hsa_fam > 0:
                dist = self.distribute_amount(hsa_fam, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('70212', amt, 0, 'Employer Ded (Expense):  HSA Family (Medical $6350)', qclass)
                    add_journal_row('70212', 0, amt, 'Employer Ded (Liability):  HSA Family (Medical $6350)', qclass)

            # HSA Match (Individual $6350)
            hsa_ind6350 = row.get('Ded-Total-HSA Individual (Medical $6350)-ER-Uncollected', 0)
            if pd.isna(hsa_ind6350): hsa_ind6350 = 0
            if hsa_ind6350 > 0:
                dist = self.distribute_amount(hsa_ind6350, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('70212', amt, 0, 'Employer Ded (Expense):  HSA Individual (Medical $6350)', qclass)
                    add_journal_row('70212', 0, amt, 'Employer Ded (Liability):  HSA Individual (Medical $6350)', qclass)

            # ---------------- EMPLOYER TAXES (Expenses) ----------------
            # Medicare ER
            mc_er = row.get('Tax-Total-Medicare-ER', 0)
            if pd.isna(mc_er): mc_er = 0
            if mc_er > 0:
                dist = self.distribute_amount(mc_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('4.7', amt, 0, 'Employer Tax (Expense):  Medicare', qclass)

            # Social Security ER
            ss_er = row.get('Tax-Total-Social Security-ER', 0)
            if pd.isna(ss_er): ss_er = 0
            if ss_er > 0:
                dist = self.distribute_amount(ss_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('4.7', amt, 0, 'Employer Tax (Expense):  Social Security', qclass)

            # FUTA ER
            futa_er = row.get('Tax-Total-FUTA-ER', 0)
            if pd.isna(futa_er): futa_er = 0
            if futa_er > 0:
                dist = self.distribute_amount(futa_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('4.7', amt, 0, 'Employer Tax (Expense):  Federal Unemployment Tax', qclass)

            # SUI ER (Georgia / Florida)
            sui_er = row.get('Tax-Total-GA-UI-ER', 0) or row.get('Tax-Total-FL-UI-ER', 0) or row.get('Tax-GA-UI-ER', 0) or row.get('Tax-FL-UI-ER', 0)
            if pd.isna(sui_er): sui_er = 0
            if sui_er > 0:
                dist = self.distribute_amount(sui_er, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('4.7', amt, 0, 'Employer Tax (Expense):  Georgia/Florida Unemployment Tax', qclass)


            # ---------------- CASH REQUIREMENTS (Credits to GL 20600) ----------------
            # Direct Deposit Net
            net_dd = row.get('Total Direct Deposit Net', 0)
            if pd.isna(net_dd): net_dd = 0
            if net_dd > 0:
                dist = self.distribute_amount(net_dd, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('20600', 0, amt, 'Payroll Cash Requirement: Direct Deposit', qclass)

            # Checks to Print
            net_chk = row.get('Total Check Net', 0)
            if pd.isna(net_chk): net_chk = 0
            if net_chk > 0:
                dist = self.distribute_amount(net_chk, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('20600', 0, amt, 'Payroll: Checks to Print', qclass)

            # Employee Taxes Cash Req
            ee_tax = row.get('Total Employee Tax', 0)
            if pd.isna(ee_tax): ee_tax = 0
            if ee_tax > 0:
                dist = self.distribute_amount(ee_tax, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('20600', 0, amt, 'Payroll Cash Requirement: Employee Taxes', qclass)

            # Employer Taxes Cash Req
            er_tax = row.get('Total Employer Tax', 0)
            if pd.isna(er_tax): er_tax = 0
            if er_tax > 0:
                dist = self.distribute_amount(er_tax, splits if is_exempt else {dept_class: 1.0})
                for qclass, amt in dist.items():
                    add_journal_row('20600', 0, amt, 'Payroll Cash Requirement: Employer Taxes', qclass)

            # Skip Employee Deductions Cash Req credit row since individual deductions are already credited
            pass

        # Add manual payroll fees if provided
        if payroll_fees > 0:
            dist_fees = self.distribute_amount(payroll_fees, overall_splits)
            for qclass, amt in dist_fees.items():
                add_journal_row('7.04.1', amt, 0, 'Payroll Processing Fees', qclass)
                add_journal_row('20600', 0, amt, 'Payroll Cash Requirement: Payroll Fees', qclass)

        output_df = pd.DataFrame(journal_rows)
        
        # 5. Aggregation
        final_df = output_df.groupby(['Date', 'GL Code', 'Memo', 'CLASS', 'NOTES'], as_index=False).agg({
            'Debit': 'sum',
            'Credit': 'sum'
        })
        
        # Enforce exact column lock schema
        final_df = final_df[['Date', 'GL Code', 'Debit', 'Credit', 'Memo', 'CLASS', 'NOTES']]

        # 6. Balancing Check
        total_debit = round(final_df['Debit'].sum(), 2)
        total_credit = round(final_df['Credit'].sum(), 2)
        
        if total_debit != total_credit:
            raise ValueError(f"Journal Entry Out of Balance! Debits: {total_debit}, Credits: {total_credit}")
            
        return final_df

class PayrollApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Payroll to QBO Converter")
        self.root.geometry("600x480")
        self.transformer = PayrollTransformer()
        
        self.file_path = tk.StringVar()
        
        # Apply modern premium dark theme styling
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Colors
        self.bg_color = "#121212"
        self.card_bg = "#1e1e1e"
        self.accent_color = "#2ca01c" # QuickBooks Green
        self.accent_hover = "#238016"
        self.text_color = "#ffffff"
        self.secondary_text = "#b0b0b0"
        
        self.root.configure(bg=self.bg_color)
        
        # Styles configuration
        self.style.configure(".", background=self.bg_color, foreground=self.text_color)
        self.style.configure("TLabel", background=self.bg_color, foreground=self.text_color, font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"), foreground=self.accent_color)
        self.style.configure("Card.TFrame", background=self.card_bg, relief="flat")
        self.style.configure("TButton", background=self.accent_color, foreground=self.text_color, font=("Segoe UI", 10, "bold"), borderwidth=0)
        self.style.map("TButton", background=[("active", self.accent_hover), ("pressed", self.accent_hover)])
        self.style.configure("Secondary.TButton", background="#3a3a3a", foreground=self.text_color)
        self.style.map("Secondary.TButton", background=[("active", "#4a4a4a")])

        # Layout
        title_frame = ttk.Frame(root)
        title_frame.pack(fill="x", padx=20, pady=15)
        ttk.Label(title_frame, text="Payroll to QBO Converter", style="Title.TLabel").pack(side="left")

        # Main Card Frame
        main_card = ttk.Frame(root, style="Card.TFrame")
        main_card.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Browse Section
        tk.Label(main_card, text="Select Payroll Complete Summary CSV file:", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 10)).pack(anchor="w", padx=20, pady=(20, 5))
        
        browse_frame = tk.Frame(main_card, bg=self.card_bg)
        browse_frame.pack(fill="x", padx=20, pady=5)
        
        self.ent_file = ttk.Entry(browse_frame, textvariable=self.file_path, width=40)
        self.ent_file.pack(side="left", padx=(0, 10), fill="x", expand=True)
        
        btn_browse = ttk.Button(browse_frame, text="Browse", command=self.browse_file)
        btn_browse.pack(side="right")
        
        # Splits Editor Trigger
        splits_frame = tk.Frame(main_card, bg=self.card_bg)
        splits_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(splits_frame, text="Manage Salaried splits:", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 10)).pack(side="left", padx=(0, 10))
        btn_splits = ttk.Button(splits_frame, text="Configure splits", style="Secondary.TButton", command=self.open_splits_window)
        btn_splits.pack(side="left")

        # Run Button
        self.btn_run = ttk.Button(main_card, text="Generate balanced QBO Journal Entry", command=self.process_data)
        self.btn_run.pack(pady=20, fill="x", padx=20)
        
        # Status Box
        tk.Label(main_card, text="Execution Log:", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 10)).pack(anchor="w", padx=20)
        self.status_text = tk.Text(main_card, height=6, width=50, bg="#121212", fg=self.accent_color, insertbackground="white", state='disabled', font=("Consolas", 9), relief="flat")
        self.status_text.pack(pady=(5, 20), padx=20, fill="both", expand=True)

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if filename:
            self.file_path.set(filename)

    def log(self, message):
        self.status_text.config(state='normal')
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(tk.END, message)
        self.status_text.config(state='disabled')

    def process_data(self):
        if not self.file_path.get():
            messagebox.showwarning("File missing", "Please select an input CSV file first.")
            return
        
        try:
            self.log("Reading file and applying transformation...\n")
            output_df = self.transformer.transform(self.file_path.get(), payroll_fees=0.0)
            
            save_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")],
                initialfile=f"QBO_Journal_Entry_{datetime.now().strftime('%Y%m%d')}.csv"
            )
            
            if save_path:
                output_df.to_csv(save_path, index=False)
                self.log(f"SUCCESS: balanced Journal Entry generated.\nDebits: {output_df['Debit'].sum():.2f} | Credits: {output_df['Credit'].sum():.2f}\nSaved to: {os.path.basename(save_path)}")
                messagebox.showinfo("Success", "QBO Journal Entry created successfully and balanced perfectly!")
                
        except Exception as e:
            self.log(f"ERROR: {str(e)}")
            messagebox.showerror("Processing Error", str(e))

    def open_splits_window(self):
        """Opens split editor window."""
        editor = tk.Toplevel(self.root)
        editor.title("Salaried Splits Configurator")
        editor.geometry("500x400")
        editor.configure(bg=self.bg_color)
        
        ttk.Label(editor, text="Salaried Splits Editor", font=("Segoe UI", 12, "bold"), foreground=self.accent_color).pack(pady=10)
        
        list_frame = ttk.Frame(editor, style="Card.TFrame")
        list_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Scrollable list of splits
        splits = self.transformer.load_splits()
        
        canvas = tk.Canvas(list_frame, bg=self.card_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=self.card_bg)
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        entries = {}
        
        def render_splits():
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            
            splits_data = self.transformer.load_splits()
            for row_idx, (emp_num, split_dict) in enumerate(splits_data.items()):
                row_f = tk.Frame(scroll_frame, bg=self.card_bg)
                row_f.pack(fill="x", pady=5, padx=5)
                
                tk.Label(row_f, text=f"Emp {emp_num}:", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 9, "bold")).pack(side="left", padx=5)
                
                split_str = ", ".join([f"{k.split(':')[-1]}:{int(v*100)}%" for k, v in split_dict.items()])
                lbl_splits = tk.Label(row_f, text=split_str, bg=self.card_bg, fg=self.secondary_text, font=("Segoe UI", 9))
                lbl_splits.pack(side="left", padx=10)
                
                # Delete Button
                btn_del = ttk.Button(row_f, text="Delete", style="Secondary.TButton", 
                                     command=lambda e=emp_num: delete_emp_split(e))
                btn_del.pack(side="right", padx=5)
        
        def delete_emp_split(emp_num):
            current_splits = self.transformer.load_splits()
            if emp_num in current_splits:
                del current_splits[emp_num]
                self.transformer.save_splits(current_splits)
                render_splits()

        def add_split():
            emp_val = ent_emp.get().strip()
            if not emp_val:
                messagebox.showerror("Error", "Employee number is required.")
                return
            
            try:
                # Basic input parse: class:pct, class:pct
                split_val = ent_split.get().strip()
                new_split = {}
                total_pct = 0
                for item in split_val.split(','):
                    parts = item.split(':')
                    if len(parts) != 2:
                        raise ValueError("Format must be class_name:percentage")
                    cname = parts[0].strip()
                    # Resolve full class name
                    full_class = cname
                    for ck, cv in self.transformer.CLASS_MAP.items():
                        if cname.lower() in cv.lower():
                            full_class = cv
                            break
                    pct = float(parts[1].strip().replace('%', '')) / 100.0
                    new_split[full_class] = pct
                    total_pct += pct
                
                if abs(total_pct - 1.0) > 0.001:
                    raise ValueError("Percentages must sum to 100%")
                
                current_splits = self.transformer.load_splits()
                current_splits[emp_val] = new_split
                self.transformer.save_splits(current_splits)
                
                ent_emp.delete(0, tk.END)
                ent_split.delete(0, tk.END)
                render_splits()
                
            except Exception as ex:
                messagebox.showerror("Format Error", f"Could not parse split: {str(ex)}\nExample format: Design:50, Enhanc:50")

        # Add new split section
        add_frame = tk.Frame(editor, bg=self.card_bg)
        add_frame.pack(fill="x", padx=20, pady=10)
        
        tk.Label(add_frame, text="Emp Number:", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ent_emp = ttk.Entry(add_frame, width=10)
        ent_emp.grid(row=0, column=1, sticky="w", padx=5, pady=2)
        
        tk.Label(add_frame, text="Split (e.g. Design:50, Maint:50):", bg=self.card_bg, fg=self.text_color, font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ent_split = ttk.Entry(add_frame, width=30)
        ent_split.grid(row=1, column=1, sticky="w", padx=5, pady=2)
        
        btn_add = ttk.Button(add_frame, text="Add/Update", command=add_split)
        btn_add.grid(row=2, column=1, sticky="e", padx=5, pady=10)
        
        render_splits()

if __name__ == "__main__":
    root = tk.Tk()
    app = PayrollApp(root)
    root.mainloop()

