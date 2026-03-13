import FinanceDataReader as fdr

print("FinanceDataReader import 성공!")

df = fdr.DataReader("005930")
print(df.tail())
