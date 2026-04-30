import pandas as pd
import os, sys

## load in master.csv
master = pd.read_csv("master.csv")
print(master)

## find the next batch of 10 PXDs that have not been reanalyzed yet
next_batch = master[master["Reannotated"] == False].head(500)
print(next_batch.to_string())

## make output df PXDs: next_batch['accession'].tolist()
output_df = pd.DataFrame({"PXDs": next_batch["accession"].tolist()})
print(output_df)

## save to csv
output_df.to_csv("next_batch.csv", index=False)

