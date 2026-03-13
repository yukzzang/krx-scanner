import FinanceDataReader as fdr
import pandas as pd

print("FinanceDataReader import 성공!")

df = fdr.DataReader("005930")
print(df.tail())
