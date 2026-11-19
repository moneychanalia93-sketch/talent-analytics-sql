-- talent-analytics-sql: secondary indexes.
-- Primary keys and UNIQUE constraints already create their own indexes. These cover
-- the foreign-key joins and filters the queries in sql/queries/ use. `python -m talentsql bench`
-- drops every index named here, times the queries, re-creates them and times again.

CREATE INDEX idx_employee_manager     ON dim_employee (manager_id);
CREATE INDEX idx_employee_hire        ON dim_employee (hire_date);
CREATE INDEX idx_employee_team_level  ON dim_employee (team, level);
CREATE INDEX idx_application_req      ON fact_application (requisition_id);
CREATE INDEX idx_application_source   ON fact_application (source, applied_at);
CREATE INDEX idx_stage_order_outcome  ON fact_stage_event (stage_order, outcome, application_id);
CREATE INDEX idx_offer_status         ON fact_offer (status, decided_date);
CREATE INDEX idx_requisition_status   ON dim_requisition (status, opened_date);
CREATE INDEX idx_requisition_team     ON dim_requisition (team);
CREATE INDEX idx_requisition_recruiter ON dim_requisition (recruiter_id);
CREATE INDEX idx_spell_employee       ON fact_employment_spell (employee_id, start_date);
CREATE INDEX idx_review_reviewer      ON fact_performance_review (reviewer_id);
CREATE INDEX idx_candidate_email      ON dim_candidate (email);
