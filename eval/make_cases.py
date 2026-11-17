"""Curated retrieval prompts based on inspected Spring Garden headings and workbook sheets."""
import json
from pathlib import Path

cases = {
'Approach Note - Change Interest Rate.docx': [
 ('direct','What is the objective of changing an interest rate?'),
 ('paraphrase','Which loans qualify for a rate modification?'),
 ('direct','How is the payment amount calculated after a rate change?'),
 ('direct','What effective date rules apply to an interest rate change?'),
 ('direct','What are the validation errors for an ineligible interest rate change?')],
'Approach Note - Interest Adjustments on Loans.docx': [
 ('direct','What is the proposed solution for interest adjustments on loans?'),
 ('direct','How do interest adjustments behave?'),
 ('direct','What special scenarios affect interest adjustments?'),
 ('direct','What system impact is described for interest adjustment?'),
 ('direct','What needs clarification before implementing interest adjustments?')],
'Approach Note - Demand Loan.docx': [
 ('direct','What is the proposed LF handling for a demand loan?'),
 ('direct','How is demand loan billing handled?'),
 ('direct','How are demand loan payments handled?'),
 ('direct','What happens when a demand loan becomes delinquent?'),
 ('direct','How is demand loan expiry tracked?')],
'Approach Note - Loan Conversion.docx': [
 ('direct','What is in scope for loan conversion?'),
 ('direct','What is out of scope for a loan conversion?'),
 ('direct','What is the proposed conversion approach?'),
 ('direct','What field validations are required during conversion?'),
 ('direct','What happens at conversion confirmation?')],
'Approach Note - Loan Tenure Extension.docx': [
 ('paraphrase','Can the repayment term be lengthened?'),
 ('direct','How is a balloon payment identified?'),
 ('direct','What is the process for extending the loan term?'),
 ('direct','How is the repayment schedule handled after a tenure extension?'),
 ('direct','How does interest accrue during a loan tenure extension?')],
'LF Handling of Special Status.docx': [
 ('direct','How should bankruptcy status be handled?'),
 ('direct','How should a deceased borrower status be handled?'),
 ('direct','How is forbearance handled for a loan?'),
 ('direct','What is the context for special status handling?'),
 ('direct','What open points remain for special status?')],
'PrePayment Penalty.xlsx': [
 ('excel','What is the prepayment penalty code?'),
 ('excel','What months elapsed bands are in the prepayment penalty calculator?'),
 ('excel','How is the prepayment penalty multiplier represented?'),
 ('excel','What follow-up questions exist for prepayment penalty?'),
 ('excel','Where is early payoff penalty defined?')],
'Spring Garden Fees - Final.xlsx': [
 ('excel','What fees are listed for Spring Garden?'),
 ('excel','What is the Fee Final applicability event?'),
 ('excel','Which fee amount rules are listed in Fee Final?'),
 ('excel','What is the fee recovery mode?'),
 ('excel','How are fees shown on the statement of account?')],
'Collateral Basic Details.xlsx': [
 ('excel','What fields are in the Collateral Final sheet?'),
 ('excel','Where is collateral mortgage date recorded?'),
 ('excel','What collateral address fields are present?'),
 ('excel','Where is the collateral registry number stored?'),
 ('excel','What collateral description fields exist?')],
'Collateral Standard LF.xlsx': [
 ('excel','What does the standard LF collateral sheet say about adding collateral?'),
 ('excel','How do users add a UCC under collateral?'),
 ('excel','Where are collateral name and address shown in the standard LF sheet?'),
 ('excel','How is collateral expanded or collapsed?'),
 ('excel','What standard LF collateral summary fields are present?')]
}
records=[{'tenant_id':'spring-garden','category':category,'question':question,'expected_document':filename}
         for filename,items in cases.items() for category,question in items]
for i,record in enumerate(records,1): record['id']=f'sg-{i:03d}'
assert len(records)==50
Path(__file__).with_name('retrieval_cases.json').write_text(json.dumps(records,indent=2)+'\n')
