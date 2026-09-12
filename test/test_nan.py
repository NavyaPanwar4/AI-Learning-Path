import pandas as pd
import numpy as np
import math

df = pd.DataFrame([
    {"rating": 5.0, "comments": "Great!"},
    {"rating": 4.0, "comments": float('nan')},
    {"rating": 3.0, "comments": None}
])

print("Original DF:")
print(df)

# Attempt 1: The current way
df1 = df.where(pd.notnull(df), None)
try:
    print("\nAttempt 1 (where notnull): ", df1.to_dict(orient='records'))
except Exception as e:
    print("\nAttempt 1 Error:", e)

# Attempt 2: using replace
df2 = df.replace({np.nan: None})
try:
    print("\nAttempt 2 (replace np.nan): ", df2.to_dict(orient='records'))
except Exception as e:
    print("\nAttempt 2 Error:", e)

# Attempt 3: fillna
try:
    df3 = df.fillna("")
    print("\nAttempt 3 (fillna empty string): ", df3.to_dict(orient='records'))
except Exception as e:
    print("\nAttempt 3 Error:", e)
