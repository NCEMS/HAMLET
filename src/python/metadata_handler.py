#!/usr/bin/env python3

import sys
import os
import argparse
import os.path
import json
def eprint(*args, **kwargs): print(*args, file=sys.stderr, **kwargs)


####################################################################################################
#### Metadata handler class
class MetadataHandler:


    ####################################################################################################
    #### Constructor
    def __init__(self, metadata_filepath=None, verbose=None, outpath:str='./'):

        ## check that the outpath exists and make it if it does not
        if not os.path.isdir(outpath):
            try:
                os.makedirs(outpath)
            except:
                eprint(f"ERROR: Cannot create output directory '{outpath}'")
                return
            
        default_metadata_filepath = os.path.join(outpath, 'study_metadata.json')

        #### Check if a metadata_filepath was provided and if not, set to default
        if metadata_filepath is None or metadata_filepath == '':
            metadata_filepath = default_metadata_filepath

        #### If this is a directory, then just append the default filename
        if os.path.isdir(metadata_filepath):
            metadata_filepath += '/' + default_metadata_filepath

        self.metadata_filepath = metadata_filepath
        self.sdrf_hints = {}
        self.sdrf_table_column_titles = []
        self.sdrf_table_rows = []

        #### Check if a verbose was provided and if not, set to default
        if verbose is None:
            verbose = 1
        self.verbose = verbose



    ####################################################################################################
    #### Create a study metadata file
    def create(self):

        file = self.metadata_filepath

        #### Comment if the file already exists
        if os.path.isfile(file):
            if self.verbose >= 1:
                eprint(f"INFO: Study metadata file '{file}' already exists. It is being overwritten.")

        if self.verbose >= 1:
            eprint(f"INFO: Creating study metadata file '{file}'")
        self.create_template()
        self.read_txt_file()
        try:
            with open(file, 'w') as outfile:
                json.dump(self.metadata, outfile, sort_keys=True, indent=2)
        except:
            eprint(f"ERROR: Cannot open file '{file}' for writing")
            return

        return 'OK'



    ####################################################################################################
    #### Read or create a study metadata file
    def read_or_create(self):

        file = self.metadata_filepath

        #### If the specified (or inferred) file does not exist, we should create it
        if not os.path.isfile(file):
            if self.verbose >= 1:
                eprint(f"INFO: Study metadata file '{file}' not found or not a file. Create it.")
            result = self.create()
            return result

        #### If there is such a file, read it
        try:
            infile = open(file, 'r')
            try:
                self.metadata = json.load(infile)
            except:
                eprint(f"ERROR: Cannot parse JSON from file '{file}'")
                return
        except:
            eprint(f"ERROR: Cannot open file '{file}' for reading")
            return

        #### Verify that this is the right kind of JSON
        n_errors = 0
        if 'knowledge' not in self.metadata or 'state' not in self.metadata:
            eprint(f"ERROR: File '{file}' is JSON, but does not appear to be a study metadata file")
            n_errors += 1

        #### Verify the version number of the file
        if 'version' not in self.metadata['state']:
            eprint(f"ERROR: File '{file}' does not have version information. Something is wrong")
            n_errors += 1
        if self.metadata['state']['version'] < 'v0.1':
            eprint(f"ERROR: Version {self.metadata['state']['version']} in file '{file}' is too old and is not supported anymore")
            n_errors += 1

        if n_errors > 0:
            return

        #### If verbose, print some information
        if self.verbose >= 1:
            eprint(f"INFO: Study metadata file '{file}' is loaded")
            eprint(f"INFO: Status is {self.metadata['state']['status']}")
            if self.metadata['state']['status'] != 'OK':
                eprint(f"INFO: Code is '{self.metadata['state']['code']}'")
                eprint(f"INFO: Message is '{self.metadata['state']['message']}'")
                return

        #### If we got this far, then everything seems okay
        return 'OK'



    ####################################################################################################
    #### Read the key-value study metadata text file
    def read_txt_file(self):

        file = self.metadata_filepath

        #### Replace .json with .txt
        if file.endswith('.json'):
            file = file.replace('.json', '.txt')
        else:
            if self.verbose >= 1:
                eprint(f"INFO: Study metadata file '{file}' does not end in .json, so cannot look for corresponding .txt file")
            return

        #### If the specified (or inferred) file does not exist, we should create it
        if not os.path.isfile(file):
            if self.verbose >= 1:
                eprint(f"INFO: Looked for but did not find study metadata key-value hints file '{file}'. File not not found or not a file.")
            return

        #### If there is such a file, read it
        try:
            infile = open(file, 'r')
        except:
            eprint(f"ERROR: Cannot open file '{file}' for reading")
            return

        sdrf_hints = { 'key_order': [], 'keys': {} }

        #### Parse the file
        n_errors = 0
        i_line = 0
        for line in infile:
            i_line += 1
            line = line.strip()
            if len(line) == 0:
                continue
            if line.startswith('#'):
                continue
            position = line.find('=')
            if position < 1:
                eprint(f"ERROR: File '{file}' has malformed key-value pair at line {i_line}: {line}")
                n_errors += 1
            key = line[0:position]
            value = line[position+1:]
            if key not in sdrf_hints['keys']:
                sdrf_hints['keys'][key] = []
                sdrf_hints['key_order'].append(key)
            sdrf_hints['keys'][key].append(value)

        self.sdrf_hints = sdrf_hints

        if n_errors > 0:
            self.metadata['state']['status'] = 'ERROR'
            self.metadata['state']['code'] = 'TxtParseError'
            self.metadata['state']['message'] = f"{n_errors} errors parsing sdrf txt hints file"

        #### If verbose, print some information
        if self.verbose >= 1:
            eprint(f"INFO: Study metadata SDRF hints text file '{file}' is loaded")
            eprint(f"INFO: Status is {self.metadata['state']['status']}")
            if self.metadata['state']['status'] != 'OK':
                eprint(f"INFO: Code is '{self.metadata['state']['code']}'")
                eprint(f"INFO: Message is '{self.metadata['state']['message']}'")
                return

        #### If we got this far, then everything seems okay
        eprint(json.dumps(sdrf_hints, indent=2, sort_keys=2))
        return 'OK'



    ####################################################################################################
    #### Create a blank template metadata object
    def create_template(self):

        self.metadata = {
            'files': {},
            'knowledge': {},
            'search_criteria': {},
            'spectra_stats': {},
            'problems': {
                'warnings': {
                    'count': 0,
                    'list': [],
                    'codes': {} },
                'errors': {
                    'count': 0,
                    'list': [],
                    'codes': {} }
            },
            'state': { 'status': 'OK', 'message': 'No problems detected', 'code': 'OK', 'version': 'v0.1' }
        }

        return self.metadata



    ####################################################################################################
    #### Store study metadata file
    def store(self):

        #metadata_output_filepath = os.path.join(outpath, self.metadata_filepath)
        if self.verbose >= 1:
            eprint(f"INFO: Writing study metadata file '{self.metadata_filepath}'")
            #eprint(f"INFO: Writing study metadata file '{metadata_output_filepath}'")

        with open(self.metadata_filepath, 'w') as outfile:
            json.dump(self.metadata,outfile, sort_keys=True, indent=2)
        #with open(metadata_output_filepath, 'w') as outfile:
        #    json.dump(self.metadata, outfile, sort_keys=True, indent=2)

        if len(self.sdrf_table_column_titles) == 0:
            return

        filename = self.metadata_filepath
        #### Replace .json with .sdrf.tsv
        if filename.endswith('.json'):
            filename = filename.replace('.json', '.sdrf.tsv')
        else:
            if self.verbose >= 1:
                eprint(f"INFO: Study metadata file '{filename}' does not end in .json, so cannot create corresponding .sdrf.tsv file")
            return

        if self.verbose >= 1:
            eprint(f"INFO: Writing SDRF file '{filename}'")
            
        with open(filename, 'w') as outfile:
            print("\t".join(self.sdrf_table_column_titles), file=outfile)
            for row in self.sdrf_table_rows:
                print("\t".join(row), file=outfile)



    ####################################################################################################
    #### Infer search criteria based on available information
    def infer_search_criteria(self):

        #### Short handle for the search criteria information
        criteria = self.metadata['search_criteria']
        knowledge = self.metadata['knowledge']
        spectra_stats = self.metadata['spectra_stats']
        verbose = self.verbose
        if verbose >= 1: eprint("INFO: Inferring search criteria from the available information")

        # Since we will recompute the numbers, zero out all the counters
        knowledge['instrument_model'] = 'unknown'
        if 'instrument_models' in knowledge:
            for instrument_model in knowledge['instrument_models']:
                knowledge['instrument_models'][instrument_model] = 0

        criteria['fragmentation_type'] = 'unknown'
        if 'fragmentation_types' in criteria:
            for fragmentation_type in criteria['fragmentation_types']:
                criteria['fragmentation_types'][fragmentation_type] = 0

        #### Loop over all the files and decide on search criteria
        for file in self.metadata['files']:
            fileinfo = self.metadata['files'][file]

            #### Assemble consensus instrument
            if 'instrument_model' in fileinfo:
                file_instrument = fileinfo['instrument_model']['name'] or 'unknown'
                if 'instrument_model' not in knowledge: knowledge['instrument_model'] = file_instrument
                if 'instrument_models' not in knowledge: knowledge['instrument_models'] = {}
                if file_instrument not in knowledge['instrument_models']: knowledge['instrument_models'][file_instrument] = 0
                knowledge['instrument_models'][file_instrument] += 1
                if knowledge['instrument_model'] == 'unknown':
                    knowledge['instrument_model'] = file_instrument
                elif knowledge['instrument_model'] == file_instrument:
                    pass
                else:
                    knowledge['instrument_model'] = 'multiple'
                    self.log_event('ERROR','MultipleInstruments',f"There are multiple instruments in this group of MS runs. Unless they are highly similar, it may be best to separate them.")
            else:
                knowledge['instrument_model'] = 'unknown'
                self.log_event('ERROR','MissingInstrument',f"The instrument was not determined. This should be handled better.")

            #### Assemble fragmentation type
            if 'fragmentation_type' in fileinfo['spectra_stats']:
                fragmentation_type = fileinfo['spectra_stats']['fragmentation_type'] or 'unknown'
                if 'fragmentation_type' not in criteria: criteria['fragmentation_type'] = fragmentation_type
                if 'fragmentation_types' not in criteria: criteria['fragmentation_types'] = {}
                if fragmentation_type not in criteria['fragmentation_types']: criteria['fragmentation_types'][fragmentation_type] = 0
                criteria['fragmentation_types'][fragmentation_type] += 1
                if criteria['fragmentation_type'] == 'unknown':
                    criteria['fragmentation_type'] = fragmentation_type
                elif criteria['fragmentation_type'] == fragmentation_type:
                    pass
                else:
                    criteria['fragmentation_type'] = 'multiple'
                    self.log_event('ERROR','MultipleFragTypes',f"There are multiple fragmentation types in this group of MS runs. Unless your search engine can handle this, you should split them.")
            else:
                criteria['fragmentation_type'] = 'unknown'
                self.log_event('ERROR','MissingFragType',f"The fragmentation type was not determined. This should be handled better.")

            #### Assemble high_accuracy_precursors
            if 'high_accuracy_precursors' not in criteria: criteria['high_accuracy_precursors'] = 'unknown'
            high_accuracy_precursors = fileinfo['spectra_stats']['high_accuracy_precursors']
            if criteria['high_accuracy_precursors'] == 'unknown':
                criteria['high_accuracy_precursors'] = high_accuracy_precursors
            elif criteria['high_accuracy_precursors'] == high_accuracy_precursors:
                pass
            else:
                criteria['high_accuracy_precursors'] = 'multiple'
                self.log_event('ERROR','MultipleFragTypes',f"There are multiple precursor accuracy types in this group of MS runs. They should probably be separated.")

            #### Assemble labeling
            if 'labeling' not in criteria: criteria['labeling'] = 'unknown'
            labeling = 'unknown'
            if 'summary' in fileinfo and 'call' in fileinfo['summary']['labeling']:
                labeling = fileinfo['summary']['labeling']['call']
                if criteria['labeling'] == 'unknown':
                    if labeling != 'ambiguous':
                        criteria['labeling'] = labeling
                elif criteria['labeling'] == labeling:
                    pass
                else:
                    if labeling != 'ambiguous':
                        criteria['labeling'] = 'multiple'
                        self.log_event('ERROR','MultipleLabelingTypes',f"There are multiple labeling types in this MS run group. Split them.")


            #### Review the acquisition types
            if 'acquisition_type' not in criteria:
                criteria['acquisition_type'] = 'unknown'
            acquisition_type = fileinfo['spectra_stats']['acquisition_type']
            if criteria['acquisition_type'] == 'unknown':
                criteria['acquisition_type'] = acquisition_type
            elif criteria['acquisition_type'] == acquisition_type:
                pass
            else:
                criteria['acquisition_type'] = 'multiple'
                self.log_event('ERROR','MultipleAcquisitionTypes',f"There are multiple acquisition types in this group of MS runs. They should probably be separated.")


            #### Roll up the spectra counts
            if 'spectra_stats' in fileinfo:
                for key,value in fileinfo['spectra_stats'].items():
                    if key.startswith('n_'):
                        if key not in spectra_stats:
                            spectra_stats[key] = 0
                        spectra_stats[key] += value



    ####################################################################################################
    #### Generate SDRF table data
    def generate_sdrf_table(self):

        self.sdrf_table_column_titles = []
        self.sdrf_table_rows = []

        if len(self.sdrf_hints['keys']) == 0:
            if verbose > 0:
                eprint(f"INFO: Skip generating an SDRF file. Study metadata txt template is not available")
            return

        sdrf_hints_to_skip = [ 'dataset_identifier', 'experiment_identifier', 'sdrf_template' ]

        for key in self.sdrf_hints['key_order']:
            if key in sdrf_hints_to_skip:
                continue
            if key not in self.sdrf_hints['keys']:
                eprint("ERROR E362")
                return
            for value in self.sdrf_hints['keys'][key]:
                self.sdrf_table_column_titles.append(key)

        files = list(self.metadata['files'])
        files.sort()
        i_sample = 1

        for file in files:
            row = []
            for key in self.sdrf_hints['key_order']:
                if key in sdrf_hints_to_skip:
                    continue
                if key not in self.sdrf_hints['keys']:
                    eprint("ERROR E362")
                    return
                for value in self.sdrf_hints['keys'][key]:

                    if value != '':
                        value += '[HUMAN]'

                    if key == 'source name':
                        value = f"sample {i_sample}[AG-TBA]"

                    if key == 'comment[proteomics data acquisition method]':
                        if value == '':
                            if self.metadata['files'][file]['spectra_stats']['acquisition_type'] == 'DDA':
                                value = 'NT=data-dependent acquisition;AC=MS:1003221[DATA-I]'
                            elif self.metadata['files'][file]['spectra_stats']['acquisition_type'] == 'DIA':
                                value = 'NT=data-independent acquisition;AC=MS:1003215[DATA-I]'

                    if key == 'comment[data file]':
                        value = f"{file}[DATA]"

                    if key == 'comment[precursor mass tolerance]':
                        if value == '':
                            if self.metadata['files'][file]['spectra_stats']['high_accuracy_precursors'] == 'true':
                                value = '20 ppm[DATA-DI]'
                            elif self.metadata['files'][file]['spectra_stats']['high_accuracy_precursors'] == 'false':
                                value = '3.1 Da[DATA-DI]'

                    if key == 'comment[fragment mass tolerance]':
                        if value == '':
                            if self.metadata['files'][file]['spectra_stats']['fragmentation_type'].startswith('HR'):
                                value = '20 ppm[DATA-DI]'
                            elif self.metadata['files'][file]['spectra_stats']['fragmentation_type'].startswith('LR'):
                                value = '0.6 Da[DATA-DI]'

                    if key == 'comment[instrument]':
                        value = f"NT={self.metadata['files'][file]['instrument_model']['name']};AC={self.metadata['files'][file]['instrument_model']['accession']}[DATA]"

                    if key == 'comment[tool metadata]':
                        value = 'RunAssessor v0.1[TOOL]'

                    row.append(value)
            self.sdrf_table_rows.append(row)

            i_sample += 1



    ####################################################################################################
    #### Log an event
    def log_event(self, status, code, message):

        category = 'UNKNOWN'
        if status == 'WARNING':
            category = 'warnings'
        elif status == 'ERROR':
            category = 'errors'
        else:
            eprint(f"FATAL ERROR: Unrecognized event status '{status}'")
            eprint(sys.exc_info())
            sys.exit()

        #### Record the event
        full_message = f"{status}: [{code}]: {message}"
        self.metadata['problems'][category]['count'] += 1
        self.metadata['problems'][category]['list'].append(full_message)
        if code not in self.metadata['problems'][category]['codes']:
            self.metadata['problems'][category]['codes'][code] = 1
        else:
            self.metadata['problems'][category]['codes'][code] += 1

        #### If this is an error, also update the overall state
        if status == 'ERROR':
            self.metadata['state']['status'] = status
            self.metadata['state']['code'] = code
            self.metadata['state']['message'] = message
            if self.verbose >= 1:
                eprint(full_message)


####################################################################################################
#### Main function for command-line usage
def main():

    #### Parse command line arguments
    argparser = argparse.ArgumentParser(description='Handler for study/experiment metadata files')
    argparser.add_argument('--metadata_filepath', action='store', help='Filepath of the metadata file (defaults to study_metadata.json)')
    argparser.add_argument('--verbose', action='count' )
    argparser.add_argument('--version', action='version', version='%(prog)s 0.5')
    params = argparser.parse_args()

    #### Create metadata handler object and read or create the metadata structure
    metadata = MetadataHandler(params.metadata_filepath, params.verbose)
    metadata.read_or_create()

    #### Try to infer search criteria based on the information we have available
    metadata.infer_search_criteria()

    #### Store the metadata structure
    metadata.store()

if __name__ == "__main__": main()
