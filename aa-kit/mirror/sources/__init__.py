"""
Counterparty Mirror - external DPI sources (Gate 5).

Each adapter turns one external lookup into a minimised, labelled SourceRecord.
Adapters never decide anything about the household: the evaluator does, from
the record's kept fields, exactly as it does from bank transactions.
"""
