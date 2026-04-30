import pandas as pd
import argparse
import glob
import json
import numpy as np
import sys
import os
from pathlib import Path

# Add parent directory to path for importing PipelineLogger
sys.path.insert(0, str(Path(__file__).parent))
from PipelineLogger import PipelineLogger

"""
Get the text files for each PXD provided as user arguments and load them 

python ../../sample_code/GetTextcsvs.py --PXDcsv Training_PXDs.csv --outpath PubText/ > logs/GetTextcsvs.log 
python ../../sample_code/GetTextcsvs.py --PXDcsv HoldoutPXDs.csv --outpath PubText/ > logs/GetTextcsvs.log
"""

ALLOWED_section_types = ['TITLE', 'ABSTRACT', 'INTRO', 'RESULTS', 'DISCUSS', 'FIG', 'METHODS', 'REF', 'SUPPL']


def extract_raw_files_from_pride_metadata(pxd: str, results_path: str, logger=None) -> list:
    """
    Extract .raw file names from PRIDEmetadata.json saved by FetchPXD.
    This eliminates dependency on PRIDEfiles_20250927.csv.
    
    Args:
        pxd: PXD identifier
        results_path: Path to results directory containing {pxd}/ subdirectories
        logger: Optional PipelineLogger instance for event logging
    
    Returns:
        List of .raw file names for this PXD
        
    Raises:
        FileNotFoundError: If PRIDEmetadata.json doesn't exist
        ValueError: If no .raw files found in metadata
    """
    metadata_file = os.path.join(results_path, f"{pxd}_PRIDEmetadata.json")
    
    if not os.path.exists(metadata_file):
        error_msg = f"PRIDEmetadata not found at {metadata_file}. Metadata must be created by FetchPXD.py before LLM extraction."
        print(f"ERROR: {error_msg}")
        if logger:
            logger.process_error("llm_extraction", error_msg, is_fatal=True)
        raise FileNotFoundError(error_msg)
    
    try:
        print(f"Loading file list from PRIDE metadata: {metadata_file}")
        with open(metadata_file, 'r') as f:
            pride_data = json.load(f)
        
        files = []
        if 'files' in pride_data:
            for file_record in pride_data['files']:
                file_name = file_record.get('fileName', '')
                if file_name.lower().endswith('.raw'):
                    files.append(file_name)
            print(f"Found {len(files)} .raw files in PRIDE metadata for {pxd}")
        
        if len(files) == 0:
            error_msg = f"No .raw files found in PRIDE metadata for {pxd}. Cannot proceed with LLM extraction."
            print(f"ERROR: {error_msg}")
            if logger:
                logger.process_error("llm_extraction", error_msg, is_fatal=True)
            raise ValueError(error_msg)
        
        return files
        
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing PRIDE metadata JSON at {metadata_file}: {e}"
        print(f"ERROR: {error_msg}")
        if logger:
            logger.process_error("llm_extraction", error_msg, is_fatal=True)
        raise ValueError(error_msg)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get text files for given PXDs.')
    parser.add_argument('--PXDcsv', metavar='PXD', type=str, help='Path to CSV file containing PXDs')
    parser.add_argument('--results_path', type=str, required=True, help='Path to results directory containing PXD subdirectories with metadata and PMC JSON')
    parser.add_argument('--outpath', type=str, help='Output path for the processed data')
    parser.add_argument('--log_file', default=None, help='Path to JSONL file for pipeline event logging')
    args = parser.parse_args()

    PXDcsv = pd.read_csv(args.PXDcsv)
    # Use 'PXD' column name (consistent with Nextflow pipeline)
    # Handle 'PXDs' as fallback for backwards compatibility
    if 'PXD' in PXDcsv.columns:
        pxds = PXDcsv['PXD'].tolist()
    elif 'PXDs' in PXDcsv.columns:
        pxds = PXDcsv['PXDs'].tolist()
    else:
        raise ValueError(f"CSV must have 'PXD' column (or 'PXDs' for backwards compatibility). Found columns: {PXDcsv.columns.tolist()}")
    pxds = np.unique(pxds).tolist()
    print(f"PXDs to process: {pxds} {len(pxds)}")

    results_path = args.results_path
    outpath = args.outpath
    print(f"Processing {len(pxds)} PXDs using results directory: {results_path}")
    print(f"Output path: {outpath}")

    outJSON = {}

    for pxd in pxds:
        # Initialize logger for this PXD
        logger = None
        if args.log_file:
            logger = PipelineLogger(args.log_file, pxd)
            logger.process_step("llm_extraction", "Starting text extraction", {"pxd": pxd})
        
        try:
            # Extract .raw file list from PRIDEmetadata.json (no external database dependency)
            files = extract_raw_files_from_pride_metadata(pxd, results_path, logger)
            
            # Look for PMC publication text (BioC JSON format)
            textjson_file_path = glob.glob(os.path.join(results_path, 'pmc_json', f"{pxd}_*.json"))
            
            if not textjson_file_path:
                error_msg = f"No PMC publication text found for {pxd} at {os.path.join(results_path, 'pmc_json')}"
                print(f"ERROR: {error_msg}")
                if logger:
                    logger.process_error("llm_extraction", error_msg, is_fatal=True)
                sys.exit(1)
            
            if len(textjson_file_path) > 1:
                print(f"Warning: Multiple text files found for {pxd}. Using the first one.")
            textjson_file_path = textjson_file_path[0]
            print(f"Using publication text from: {textjson_file_path}")

            text_row = {section: '' for section in ALLOWED_section_types}
            try:
                # load json into dictionary
                with open(textjson_file_path, 'r') as f:
                    text_data = json.load(f)

                # BioC JSON from PMC is an array; access the first item which contains documents
                if not text_data or len(text_data) == 0:
                    raise ValueError(f"Empty BioC JSON array for {pxd}")
                
                bioc_item = text_data[0]
                for doc in bioc_item.get('documents', []):
                    for passage in doc.get('passages', []):
                        text = passage['text']
                        section_type = passage.get('infons', {}).get('section_type', 'Unknown')
                        if section_type in ALLOWED_section_types:
                            if text_row[section_type] == '':
                                text_row[section_type] = text
                            else:
                                text_row[section_type] += '\n' + text
                    break
                
                if logger:
                    logger.process_step("llm_extraction", "Publication text extracted", {"pxd": pxd, "sections": len([s for s in text_row.values() if s])})

            except FileNotFoundError:
                error_msg = f"Text file for {pxd} not found at {textjson_file_path}. Skipping."
                print(f"ERROR: {error_msg}")
                if logger:
                    logger.process_error("llm_extraction", error_msg, is_fatal=True)
                sys.exit(1)
            except Exception as e:
                error_msg = f"Error loading {textjson_file_path}: {e}"
                print(f"ERROR: {error_msg}")
                if logger:
                    logger.process_error("llm_extraction", error_msg, is_fatal=True)
                sys.exit(1)

        except (FileNotFoundError, ValueError) as e:
            error_msg = f"Failed to extract metadata/files for {pxd}: {e}"
            print(f"ERROR: {error_msg}")
            if logger:
                logger.process_error("llm_extraction", error_msg, is_fatal=True)
            sys.exit(1)

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
                    # Can't use backslash in f-string expression, so use join outside
                    files_text = '\n'.join(txt)
                    f.write(f"{section}:\n{files_text}\n\n")
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

 