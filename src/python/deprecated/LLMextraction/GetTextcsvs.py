import pandas as pd
import argparse
import glob
import json
import numpy as np
"""
Get the text files for each PXD provided as user arguments and load them 

python ../../sample_code/GetTextcsvs.py --PXDcsv Training_PXDs.csv --outpath PubText/ > logs/GetTextcsvs.log 
python ../../sample_code/GetTextcsvs.py --PXDcsv HoldoutPXDs.csv --outpath PubText/ > logs/GetTextcsvs.log
"""
PRIDEfiles = '/home/ians/HAMLET/data/20250927/PRIDEfiles_20250927.csv'
PRIDEfiles = pd.read_csv(PRIDEfiles)
print(PRIDEfiles)

ALLOWED_section_types = ['TITLE', 'ABSTRACT', 'INTRO', 'RESULTS', 'DISCUSS', 'FIG', 'METHODS', 'REF', 'SUPPL']

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get text files for given PXDs.')
    parser.add_argument('--PXDcsv', metavar='PXD', type=str, help='Path to CSV file containing PXDs')
    parser.add_argument('--database', type=str, default='/home/ians/HAMLET/data/20250927/')
    parser.add_argument('--outpath', type=str, help='Output path for the processed data')
    args = parser.parse_args()


    PXDcsv = pd.read_csv(args.PXDcsv)
    pxds = PXDcsv['PXDs'].tolist()
    pxds = np.unique(pxds).tolist()
    print(f"PXDs to process: {pxds} {len(pxds)}")

    database_path = args.database
    outpath = args.outpath
    print(f"Fetching text files for PXDs: {pxds} {len(pxds)} from database: {database_path}")
    print(f"Output path: {outpath}")

    outJSON = {}

    for pxd in pxds:
        textjson_file_path = glob.glob(f"{database_path}/pmc_json/{pxd}_*.json")
        if not textjson_file_path:
            print(f"Warning: No text file found for {pxd} in {database_path}. Skipping.")
            quit()
        if len(textjson_file_path) > 1:
            print(f"Warning: Multiple text files found for {pxd} in {database_path}. Using the first one.")
        textjson_file_path = textjson_file_path[0]
        # print(f"Loading text file for {pxd} from {textjson_file_path}")

        text_row = {'TITLE': '', 'ABSTRACT': '', 'INTRO': '', 'RESULTS': '', 'DISCUSS': '', 'FIG': '', 'METHODS': ''}
        try:
            # load json into dictionary
            with open(textjson_file_path, 'r') as f:
                text_data = json.load(f)

            for doc in text_data['documents']:
                for passage in doc['passages']:
                    text = passage['text']
                    section_type = passage.get('infons', {}).get('section_type', 'Unknown')
                    if section_type in ALLOWED_section_types:
                        if text_row[section_type] == '':
                            text_row[section_type] = text
                        else:
                            text_row[section_type] += '\n' + text
                break

        except FileNotFoundError:
            print(f"Warning: Text file for {pxd} not found at {textjson_file_path}. Skipping.")
        except Exception as e:
            print(f"Error loading {textjson_file_path}: {e}")


        # Check for file names 
        PXD_PRIDE_files = PRIDEfiles[PRIDEfiles['PRIDE_PXD'] == pxd]
        PXD_PRIDE_files = PXD_PRIDE_files[PXD_PRIDE_files['file_name'].str.endswith('.raw')]

        print(f"Found {len(PXD_PRIDE_files)} RAW files for {pxd} in PRIDEfiles.\n{PXD_PRIDE_files}")
        files = PXD_PRIDE_files['file_name'].tolist()
        if len(files) == 0:
            # raise ValueError(f"Warning: No RAW files found for {pxd}. Skipping.")
            print(f"Warning: No RAW files found for {pxd}. Skipping.")

        text_row['Raw Data Files'] = files


        # add to master outJSON
        outJSON[pxd] = text_row
        

        # add text columns to new_df = pxd_df.copy() right after PXD column
        outfile = f"{outpath}/{pxd}_PubText.txt"
        print(f"Writing text data for {pxd} to {outfile}")
        with open(outfile, 'w') as f:
            for section, txt in text_row.items():
                if section != 'Raw Data Files':
                    f.write(f"{section}:\n{txt}\n\n")
                else:
                    f.write(f"{section}:\n{'\n'.join(txt)}\n\n")
        print(f"Wrote text data for {pxd} to {outfile}")


        # save it as a .json entry too
        outfile = f"{outpath}/{pxd}_PubText.json"
        with open(outfile, 'w') as f:
            json.dump(text_row, f, indent=4)
        print(f"Wrote text data for {pxd} to {outfile}")


    # save outJSON to a file
    outJSON_file = f"{outpath}/PubText.json"
    with open(outJSON_file, 'w') as f:
        json.dump(outJSON, f, indent=4)
    print(f"Wrote all text data to {outJSON_file}")

print('NORMAL TERMINATION OF SCRIPT')

 