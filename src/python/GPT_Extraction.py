from openai import OpenAI
import argparse
import os 
import logging
import glob
import numpy as np
from multiprocessing import Pool
import multiprocessing

"""
python ../../sample_code/GPT_Extraction.py --inpath PubText/PubText.json --prompt ../prompt/Hari_prompt.txt --outpath GPT_Extract/
nohup python ../../sample_code/GPT_Extraction.py --inpath PubText/PubText.json --prompt ../prompt/BaselinePrompt.txt --outpath GPT_Extract/ > logs/GPT_Extraction_01152025.log 2>&1 &
"""
# Define model to use
# MODEL = "o4-mini-2025-04-16" 
MODEL = "gpt-5-mini-2025-08-07"

########################################################################################################
def CallGPT(text, prompt, client, MODEL):
    messages=[
        {"role": "system", "content": prompt},
        {"role": "user", "content": text },
    ]

    # Proceed with API call only if token count >= 10,000
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=messages,  
            store=True,
            timeout=9000)
    except Exception as e:
        print(f"Error during API call: {e}")
        logging.error(f"Error during API call: {e}")
        return f"Error: {e}"
    
    print(f"API call successful. Model: {MODEL}, Tokens used: {completion.usage.total_tokens}")
    logging.info(f"API call successful. Model: {MODEL}, Tokens used: {completion.usage.total_tokens}")

    return completion.choices[0].message.content
########################################################################################################

########################################################################################################
    
########################################################################################################
def process_pxd(args_tuple):
    """Worker function to process a single PXD"""
    pxd, pxd_data, prompt, MODEL, OUTPUT_DIR = args_tuple
    
    # Create OpenAI client in each process
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    print(f'\n{"#"*20}\nProcessing PXD: {pxd}\n{"#"*20}')
    pubtext = ''
    for section, text in pxd_data.items():
        if section in ['TITLE', 'ABSTRACT', 'RESULTS', 'METHODS']:
            print(f'PXD: {pxd}, Section: {section}, Text length: {len(text)} characters')
            pubtext += f'{section}:\n{text}\n\n'
        if section == 'Raw Data Files':
            pubtext += f'Raw Data Files:\n'
            for file in text:
                pubtext += f'- {file}\n'
    print(pubtext)

    # do the GPT call and write the file
    metadata = CallGPT(pubtext, prompt, client, MODEL)
    print(f'Extracted metadata: {metadata}')

    output_file = os.path.join(OUTPUT_DIR, f'{pxd}_Metadata.json')
    with open(output_file, 'w') as out_f:
        out_f.write(metadata)
    print(f'Metadata saved to {output_file}')
    
    return pxd

########################################################################################################
def main():

    #############################################################
    parser = argparse.ArgumentParser(description="Extract metadata in SDRF format from a manuscript using OpenAI API")
    parser.add_argument("--inpath", required=True, type=str, help="Path to input JSON file containing manuscript text")
    parser.add_argument("--prompt", required=True, type=str, help="Path to the prompt file that will be used to extract metadata from the manuscript")
    parser.add_argument("--outpath", required=True, type=str, help="Optional single file to process")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers (default: 4)")
    parser.add_argument("--PXD", type=str, default=None, help="Optional single PXD to process")
    args = parser.parse_args()

    # Create output directory if it doesn't exist
    OUTPUT_DIR = os.path.join(args.outpath, MODEL)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f'MADE: {OUTPUT_DIR}')
    print(f'Using {args.workers} parallel workers')
    #############################################################

    #############################################################
    ## load the prompt file if provided
    if args.prompt:
        if not os.path.isfile(args.prompt):
            ValueError(f'Prompt file {args.prompt} does not exist. Exiting.')
        with open(args.prompt, 'r') as f:
            prompt = f.read()
        print(f'Loaded prompt from {args.prompt}')
        logging.info(f'Loaded prompt from {args.prompt}')
    else:
        raise ValueError('No prompt file provided. Exiting...')
    print(f'{"#"*50}\nPROMPT:\n{prompt}\n{"#"*50}')
    #############################################################

    #############################################################
    # check that args.inpath ends in .json and load it in 
    if not args.inpath.endswith('.json'):
        raise ValueError(f'Input path {args.inpath} does not end in .json. Exiting...')
    else:
        import json
        with open(args.inpath, 'r') as f:
            data = json.load(f)
        print(f'Loaded JSON data from {args.inpath} with {len(data)} entries.')
    # print(data)
    #############################################################

    #############################################################
    # Prepare arguments for multiprocessing
    if args.PXD:
        if args.PXD not in data:
            raise ValueError(f'PXD {args.PXD} not found in input data. Exiting...')
        print(f'Processing single PXD: {args.PXD}')
        worker_args = [(args.PXD, data[args.PXD], prompt, MODEL, OUTPUT_DIR)]
    else:
        worker_args = [(pxd, data[pxd], prompt, MODEL, OUTPUT_DIR) for pxd in data]
    
    # Process PXDs in parallel
    with Pool(processes=args.workers) as pool:
        results = pool.map(process_pxd, worker_args)
    
    print(f'\nProcessed {len(results)} PXDs successfully')
    #############################################################


if __name__ == "__main__":
    main()
print('NORMAL TERMINATION')
