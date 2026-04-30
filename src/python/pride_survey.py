import pandas as pd
import glob
import requests
import sys
import os
import argparse
import json

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pride_client
from pmc_client import PMCClient
from llm_client import LLMClient


#######################################################################
def main():

    """Survey PRIDE projects and extract relevant information for downstream analysis and reannotation efforts."""
    parser = argparse.ArgumentParser(description='Survey PRIDE projects and extract relevant information.')
    parser.add_argument('--update_pride_cache', action='store_true', help='Whether to update the local cache of PRIDE projects. Default is False.')
    parser.add_argument('--update_pmc_cache', action='store_true', help='Whether to update the local cache of PMC full text. Default is False.')
    parser.add_argument('--outdir', type=str, default='./pride_survey/', help='Path to output directory for survey results. Default is ./pride_survey/')
    parser.add_argument('--prompt', default='assets/prompts/minimal_lipms.txt', help='Optional prompt to display before starting the survey.')
    args = parser.parse_args()
    print(f"Starting PRIDE survey with update_pride_cache={args.update_pride_cache}, update_pmc_cache={args.update_pmc_cache} and outdir='{args.outdir}'")
    #######################################################################

    #######################################################################
    ## For each project get the:
    #  1. accession
    #  2. pubmed_id and pmc_id
    #  3. number of files that end in .raw or .RAW
    #  4. organism
    #  5. experimentTypes
    # and add a row to an output dataframe
    ## define output file path and check if it exists. If it does, read it in and print a message. If not, create a new dataframe by fetching project data from PRIDE and extracting the required information, then save it to the output file.
    outfile = os.path.join(args.outdir, 'pride_projects_survey.csv')
    if os.path.exists(outfile):
        df_output = pd.read_csv(outfile)
        print(f"Found existing survey file with {len(df_output)} rows. It will be overwritten with new data.")

    else:

        ## Get all the project files for a given project
        Pclient = pride_client.PrideClient()
        pride_cache_path = os.path.join(args.outdir, 'pride_cache')
        available_pxds = Pclient.fetch_all_projects(cache_path=pride_cache_path, update=args.update_pride_cache)
        print(f"Number of Available projects: {len(available_pxds)}")

        print(f"No existing survey file found. A new file will be created at {outfile}.")
        pmc_client = PMCClient()
        output_rows = []

        pmc_cache_dir = os.path.join(args.outdir, 'pmc_cache')
        # os.makedirs(pmc_cache_dir, exist_ok=True)
        pmc_cache = {}
        for project_i, project in enumerate(available_pxds):
            accession = project.get('accession', '')
            print(f"\nProcessing project {project_i + 1}/{len(available_pxds)}: {accession}")
            

            ## Extract pubmed_id and pmc_id from references
            pubmed_id = ''
            pmc_id = ''
            references = project.get('references', [])
            if references:
                pubmed_id = references[0].get('pubmedID', '')

                # Convert PMID to PMCID if available
                if pubmed_id:
                    pmc_id = pmc_client.pmid_to_pmcid(str(pubmed_id)) or ''
                    if pmc_id:
                        print(f"Found PubMed ID: {pubmed_id} -> PMCID: {pmc_id}")
                        if args.update_pmc_cache:
                            pmc_response = pmc_client.fetch_full_text(pmc_id)
                            if pmc_response != None:
                                full_text = pmc_client.extract_text_sections(pmc_response)
                                full_text = [f'{section}\n{text}' for section, text in full_text.items()]
                                full_text = '\n'.join(full_text)
                                print(f"Extracted full text for PMCID {pmc_id}. Length of text: {len(full_text)} characters.\n{full_text[:50]}...")  # Print the first 500 characters of the full text
                                pmc_cache[accession] = {'pmc_id': pmc_id, 'full_text': full_text, 'pmc_response': pmc_response}
        

            # Count .raw and .RAW files
            raw_files = 0
            files = project.get('files', [])
            for file in files:
                filename = file.get('fileName', '')
                if filename.lower().endswith('.raw'):
                    raw_files += 1
            
            # Extract organism names
            organisms = project.get('organisms', [])
            organism_names = [org.get('name', '') for org in organisms]
            organism = '; '.join(organism_names)
            
            # Extract experiment types
            experiment_types = project.get('experimentTypes', [])
            experiment_type_names = [exp.get('name', '') for exp in experiment_types]
            experiment_type = '; '.join(experiment_type_names)
            
            # Search all project as a text string for Limited Proteolysis in experiment signifying substrings and add a column for it
            lip_substrings = ['limited proteolysis', 'limited proteolysis mass spectrometry', 'limited proteolysis coupled with mass spectrometry', 'limited proteolysis-mass spectrometry', 'lip-ms', 'lipms']
            project_text = str(project).lower()
            if any(substring in project_text for substring in lip_substrings):
                lip_data = True
            else:                
                lip_data = False

            # Create row and add to output
            row = {
                'accession': accession,
                'pubmed_id': pubmed_id,
                'pmc_id': pmc_id,
                'raw_file_count': raw_files,
                'organism': organism,
                'experiment_types': experiment_type,
                'limited_proteolysis': lip_data
            }
            output_rows.append(row)
            print(row)
        

        ## save pmc cache to a json file for later use
        if args.update_pmc_cache:
            with open(pmc_cache_dir, "w", encoding="utf-8") as handle:
                json.dump(pmc_cache, handle)
            print(f"PMC cache saved to {pmc_cache_dir}")


        # Create dataframe and save to CSV
        df_output = pd.DataFrame(output_rows)
        df_output.to_csv(outfile, index=False)

    print(f"\nSurvey complete. Saved {len(df_output)} projects to {outfile}.")
    print(f"\nFirst few rows:")
    print(df_output.head())

    ## load PMC cache if it exists
    pmc_cache_dir = os.path.join(args.outdir, 'pmc_cache')
    if os.path.exists(pmc_cache_dir):
        with open(pmc_cache_dir, "r", encoding="utf-8") as handle:
            pmc_cache = json.load(handle)
        print(f"PMC cache loaded from {pmc_cache_dir}. Number of entries: {len(pmc_cache)}")
    
    ## load pride cache if it exists
    pride_cache_path = os.path.join(args.outdir, 'pride_cache')
    if os.path.exists(pride_cache_path):
        Pclient = pride_client.PrideClient()
        available_pxds = Pclient.fetch_all_projects(cache_path=pride_cache_path, update=args.update_pride_cache)
        print(f"PRIDE cache loaded from {pride_cache_path}. Number of projects: {len(available_pxds)}")
    #######################################################################


    #######################################################################
    ## SELECTING LIPMS PROJECTS
    lipms_df = df_output[df_output['limited_proteolysis'] == True]
    print(f"\nNumber of projects with limited proteolysis data: {len(lipms_df)}")
    print(f"\nFirst few rows of limited proteolysis projects:")
    print(lipms_df.head())
    # save to csv
    lipms_outfile = os.path.join(args.outdir, 'lipms_outfile.csv')
    lipms_df.to_csv(lipms_outfile, index=False)
    print(f"\nLimited proteolysis projects saved to {lipms_outfile}.")
    quit()

    for rowi, row in lipms_df.iterrows():
        accession = row['accession']
        pmc_id = row['pmc_id']
        print(f"\nProject {accession} has PMCID {pmc_id}.")

        # check if accession in PMC cache        if pmc_id in pmc_cache:
        print(f"Found PMCID {pmc_id} in PMC cache for project {accession}.")
        full_text = ''
        if accession in pmc_cache:
            pmc_response = pmc_cache[accession]['pmc_response']
            full_text = pmc_cache[accession]['full_text']
        print(f"Full text length for PMCID {pmc_id}: {len(full_text)} characters.\n{full_text[:50]}...")  # Print the first 500

        # check for pride data availability in pride cache
        print(f"Checking PRIDE cache for project {accession}.")
        pride_project = next((proj for proj in available_pxds if proj.get('accession', '') == accession), None)
        if pride_project:
            print(f"Found project {accession} in PRIDE cache.")
            print(pride_project, pride_project.keys())
            files = pride_project.get('files', [])
            raw_files = [file for file in files if file.get('fileName', '').lower().endswith('.raw')]
            print(f"Project {accession} has {len(raw_files)} raw files.")

            pride_text = '\n'.join([f"{key}\n{value}" for key, value in pride_project.items() if key in ['projectDescription', 'sampleProcessingProtocol', 'dataProcessingProtocol']])
            print(f"Extracted PRIDE text for project {accession}. Length of text: {len(pride_text)} characters.\n{pride_text[:50]}...")  # Print the first 500 characters of the PRIDE text

            full_text += '\n' + pride_text
            print(f"Combined full text length for PMCID {pmc_id} and PRIDE project {accession}: {len(full_text)} characters.\n{full_text[:50]}...")  # Print the first 500 characters of the combined text

        ## use llm_client make the openAI api call with the prompt and full_text
        with open(args.prompt, "r", encoding="utf-8") as handle:
            prompt = handle.read()
        # print(f"\nUsing prompt from {args.prompt}:\n{prompt}")
        
        # Initialize LLM client and make API call
        llm_client = LLMClient()
        llm_response = llm_client.query(prompt=prompt, text=full_text)
        print(f"\nLLM Response for project {accession}:\n{llm_response}")


        # save the results to an llm cache where the key is the accession and the value is the llm_response
        llm_cache_dir = os.path.join(args.outdir, 'llm_cache')
        with open(llm_cache_dir, "w", encoding="utf-8") as handle:
            json.dump({accession: llm_response}, handle)
        print(f"LLM response saved to {llm_cache_dir} for project {accession}.")

        
    quit()
    #######################################################################



    quit()
    #######################################################################
    ## Select subset of projects that are within scope
    master_file = os.path.join(args.outdir, 'master.csv')
    df = df_output[df_output['raw_file_count'] > 0]
    df = df[df['pmc_id'] != '']
    df = df[df['pmc_id'].notna()]  # Remove rows where pmc_id is NaN
    # sort by raw file count in descending order
    df = df.sort_values(by='raw_file_count', ascending=True).reset_index(drop=True)
    df['Reannotated'] = False  # Add a column to track reannotation status
    df['Reannotation_QC'] = False  # Add a column to track QC status
    df.to_csv(master_file, index=False)
    print(f"\nNumber of projects with raw files and PMCID: {len(df)}")
    print(f"\nFirst few rows of filtered projects:")
    print(df.head())
    #######################################################################

    #######################################################################
    ## plot a cdf of the raw file counts
    import matplotlib.pyplot as plt
    cdf_file = os.path.join(args.outdir, 'master_raw_file_counts_cdf.png')
    plt.figure(figsize=(8, 6))
    plt.hist(df['raw_file_count'], bins=300, cumulative=True, density=True, histtype='step', edgecolor='blue', linewidth=2)
    plt.title('CDF of Raw File Counts in PRIDE Projects')
    plt.xlabel('Number of Raw Files')
    plt.ylabel('Cumulative Probability')
    plt.grid()
    plt.xlim(0,500)
    plt.savefig(cdf_file)
    print(f"\nCDF plot saved to {cdf_file}.")
    # plt.show()
    #######################################################################

#######################################################################
if __name__ == "__main__":
    main()
#######################################################################