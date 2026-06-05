import pytest
import pandas as pd
import os
from app import PayrollTransformer

def test_pii_stripping():
    # Verify that clean_data strips the specified PII columns
    sample_df = pd.DataFrame({
        'SSN': ['000-00-0000'],
        'First Name': ['John'],
        'Last Name': ['Doe'],
        'Employee ID': ['1234'],
        'Birth Date': ['1980-01-01'],
        'Employee Number': [1001],
        'Division Name': ['Connect']
    })
    
    transformer = PayrollTransformer()
    cleaned = transformer.clean_data(sample_df)
    assert 'SSN' not in cleaned.columns
    assert 'First Name' not in cleaned.columns
    assert 'Last Name' not in cleaned.columns
    assert 'Employee ID' not in cleaned.columns
    assert 'Birth Date' not in cleaned.columns
    assert 'Employee Number' in cleaned.columns
    assert 'Division Name' in cleaned.columns

def test_class_mapping():
    transformer = PayrollTransformer()
    assert transformer.CLASS_MAP['Connect'] == '01-ATL:Connect'
    assert transformer.CLASS_MAP['Design Build'] == '01-ATL:Design'
    assert transformer.CLASS_MAP['Enhancement'] == '01-ATL:Enhanc'
    assert transformer.CLASS_MAP['Maintenance'] == '01-ATL:Maint'

def test_balancing_logic(tmp_path):
    # Create simple balancing hourly data
    # Debit Wages: 1000.00
    # Credit Liabilities: Direct Deposit 980.00 + Medical HSA Plan 20.00 = 1000.00
    sample_data = pd.DataFrame({
        'Employee Number': [1001],
        'Overtime Status': ['Non Exempt'],
        'Department Name': ['Connect'],
        'Division Name': ['Connect'],
        'Wages-Regular-Connect': [1000.00],
        'Total Direct Deposit Net': [980.00],
        'Ded-Medical-Uncollected': [20.00],
        'Total Uncollected Deductions': [20.00]
    })
    
    input_file = tmp_path / "simple_test_input.csv"
    sample_data.to_csv(input_file, index=False)
    
    transformer = PayrollTransformer()
    result_df = transformer.transform(input_file)
    
    # Check balancing
    assert result_df['Debit'].sum() == result_df['Credit'].sum()
    assert result_df['Debit'].sum() == 1000.00

def test_unbalanced_error(tmp_path):
    # Unbalanced data should raise ValueError
    bad_data = pd.DataFrame({
        'Employee Number': [1001],
        'Overtime Status': ['Non Exempt'],
        'Department Name': ['Connect'],
        'Division Name': ['Connect'],
        'Wages-Regular-Connect': [1000.00],
        'Total Direct Deposit Net': [500.00] # Credit missing 500
    })
    input_file = tmp_path / "bad_input.csv"
    bad_data.to_csv(input_file, index=False)
    
    transformer = PayrollTransformer()
    with pytest.raises(ValueError, match="Out of Balance"):
        transformer.transform(input_file)

def test_real_world_payroll_balancing():
    input_file = "Complete Summary - Project Tracking_2743991.csv"
    assert os.path.exists(input_file), f"Client input file {input_file} not found in workspace."
    
    transformer = PayrollTransformer()
    result_df = transformer.transform(input_file)
    
    # Assert column lock order is strictly enforced
    expected_cols = ['Date', 'GL Code', 'Debit', 'Credit', 'Memo', 'CLASS', 'NOTES']
    assert list(result_df.columns) == expected_cols
    
    # Assert output is not empty
    assert len(result_df) > 0
    
    # Assert total Debits equals total Credits (balanced check)
    total_debit = round(result_df['Debit'].sum(), 2)
    total_credit = round(result_df['Credit'].sum(), 2)
    assert total_debit == total_credit, f"Debits: {total_debit} does not equal Credits: {total_credit}"
    
    # Assert transaction date is extracted as '2026-05-14'
    assert (result_df['Date'] == '2026-05-14').all(), "Not all transaction dates are 2026-05-14"
    
    # Assert that no PII column details are in the output (they shouldn't be mapped to any QBO output field)
    for pii in PayrollTransformer.PII_COLUMNS:
        assert pii not in result_df.columns

def test_feedback_v2_runs():
    import glob
    transformer = PayrollTransformer()
    files = glob.glob('FeedbackV2/Complete Summary - Project Tracking_*.csv')
    assert len(files) > 0, "No CSV files found in FeedbackV2/"
    
    for f in files:
        # Test without fees
        res_df = transformer.transform(f, payroll_fees=0.0)
        total_debit = round(res_df['Debit'].sum(), 2)
        total_credit = round(res_df['Credit'].sum(), 2)
        assert total_debit == total_credit, f"File {f} without fees is out of balance! Debits: {total_debit}, Credits: {total_credit}"
        
        # Test with fees
        res_df_fees = transformer.transform(f, payroll_fees=340.88)
        total_debit_fees = round(res_df_fees['Debit'].sum(), 2)
        total_credit_fees = round(res_df_fees['Credit'].sum(), 2)
        assert total_debit_fees == total_credit_fees, f"File {f} with fees is out of balance! Debits: {total_debit_fees}, Credits: {total_credit_fees}"
        
        # Verify that fee difference is exactly 340.88
        assert round(total_debit_fees - total_debit, 2) == 340.88

