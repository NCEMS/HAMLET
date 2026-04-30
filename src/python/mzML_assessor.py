#!/usr/bin/env python3

import sys
import os
import glob
import argparse
import os.path
import timeit
import re
import numpy
import gzip
from lxml import etree
from multiprocessing.pool import ThreadPool
def eprint(*args, **kwargs): print(*args, file=sys.stderr, **kwargs)

#### Import technical modules and pyteomics
import matplotlib.pyplot as plt
from scipy.stats import norm
from scipy.optimize import curve_fit
from pyteomics import mzml, auxiliary

#### Import the metadata handler
from metadata_handler import MetadataHandler


####################################################################################################
#### mzML Assessor class
class MzMLAssessor:


    ####################################################################################################
    #### Constructor
    def __init__(self, mzml_file, metadata=None, verbose=None):
        self.mzml_file = mzml_file

        #### Store the provided metadata or create a template to work in
        if metadata is None:
            self.metadata = { 'files': { mzml_file: {} } }
        else:
            self.metadata = metadata
            metadata['files'][mzml_file] = {}

        #### Create a place to store our composite spectra for analysis
        self.composite = {}

        #### Create a storage area for referenceable param groups, which are not really handled by pyteomics
        self.referenceable_param_group_list = {}

        #### Set verbosity
        if verbose is None: verbose = 0
        self.verbose = verbose


    ####################################################################################################
    #### Read spectra
    def read_spectra(self, write_fragmentation_type_file=None):

        #### Set up information
        t0 = timeit.default_timer()
        stats = {
            'n_spectra': 0,
            'n_ms0_spectra': 0,
            'n_ms1_spectra': 0,
            'n_ms2_spectra': 0,
            'n_ms3_spectra': 0,
            'n_length_zero_spectra': 0,
            'n_length_lt10_spectra': 0,
            'n_HR_HCD_spectra': 0,
            'n_LR_HCD_spectra': 0,
            'n_HR_IT_CID_spectra': 0,
            'n_LR_IT_CID_spectra': 0,
            'n_HR_IT_ETD_spectra': 0,
            'n_LR_IT_ETD_spectra': 0,
            'n_HR_EThcD_spectra': 0,
            'n_LR_EThcD_spectra': 0,
            'n_HR_ETciD_spectra': 0,
            'n_LR_ETciD_spectra': 0,
            'n_HR_QTOF_spectra': 0,
            'n_unknown_fragmentation_type_spectra': 0,
            'high_accuracy_precursors': 'unknown',
            'fragmentation_type': 'unknown',
            'fragmentation_tag': 'unknown'
        }
        self.metadata['files'][self.mzml_file]['spectra_stats'] = stats

        #### Store the fragmentation types in a list for storing in the fragmentation_type_file
        scan_fragmentation_list = []

        #### Show information
        if self.verbose >= 1:
            eprint(f"\nINFO: Assessing mzML file {self.mzml_file}", end='', flush=True)
            progress_intro = False

        #### If the mzML is gzipped, then open with zlib, else a plain open
        if self.mzml_file.endswith('.gz'):
            infile = gzip.open(self.mzml_file)
        else:
            infile = open(self.mzml_file, 'rb')

        #### Try storing all spectra for multithreaded processing
        #spectra = []

        #### Read spectra from the file
        with mzml.read(infile) as reader:
            #try:
            if True:
                for spectrum in reader:

                    #### Debugging. Print the data structure of the first spectrum
                    #if stats['n_spectra'] == 0:
                    #    auxiliary.print_tree(spectrum)
                    #    print(spectrum)
                    #    return

                    #### Extract the MS level of the spectrum
                    try:
                        ms_level = spectrum['ms level']
                    #### If no MS level is found, see if it can be extracted from a referenceable param group
                    except:
                        ms_level = 0
                        if 'ref' in spectrum:
                            group_id = spectrum['ref']
                            if group_id in self.referenceable_param_group_list and 'ms level' in self.referenceable_param_group_list[group_id]:
                                ms_level = int(self.referenceable_param_group_list[group_id]['ms level'])

                    #### Look for a filter string and parse it
                    if 'filter string' in spectrum['scanList']['scan'][0]:
                        filter_string = spectrum['scanList']['scan'][0]['filter string']
                        if filter_string is not None and filter_string != '':
                            self.parse_filter_string(filter_string,stats)
                        else:
                            #### MSFragger generated mzML can have empty filter strings
                            self.log_event('WARNING','EmptyFilterLine',f"Filter line is present but empty. This can happen with MSFragger-written mzML. Not good.")
                            stats[f"n_ms{ms_level}_spectra"] += 1
                            stats['high_accuracy_precursors'] = 'unknown'
                            stats['fragmentation_type'] = 'unknown_fragmentation_type'
                            stats['fragmentation_tag'] = 'unknown fragmentation type'
                            if ms_level > 1:
                                stats['n_unknown_fragmentation_type_spectra'] += 1


                    #### There's only a filter string for Thermo data, so for others, record a subset of information
                    else:
                        stats[f"n_ms{ms_level}_spectra"] += 1
                        if self.metadata['files'][self.mzml_file]['instrument_model']['category'] == 'QTOF':
                            stats['high_accuracy_precursors'] = 'true'
                            stats['fragmentation_type'] = 'HR_QTOF'
                            stats['fragmentation_tag'] = 'HR QTOF'
                            if ms_level > 1:
                                stats['n_HR_QTOF_spectra'] += 1

                    #### If the ms level is greater than 2, fail
                    if ms_level > 4:
                        self.log_event('ERROR','MSnTooHigh',f"MS level is greater than we can handle at '{spectrum['ms level']}'")
                        break

                    #### If the ms level is 2, then examine it for information
                    if ms_level == 2 and 'm/z array' in spectrum:
                        try:
                            precursor_mz = spectrum['precursorList']['precursor'][0]['selectedIonList']['selectedIon'][0]['selected ion m/z']
                        except:
                            precursor_mz = 0.0

                        #### Try to get the charge information
                        try:
                            charge_state = int(spectrum['precursorList']['precursor'][0]['selectedIonList']['selectedIon'][0]['charge state'])
                        except:
                            charge_state = 'unknown'
                        charge_stat = f"n_charge_{charge_state}_precursors"
                        if charge_stat not in stats:
                            stats[charge_stat] = 0
                        stats[charge_stat] += 1

                        #### Extract the isolation window information
                        self.record_isolation_window_stats(spectrum, stats)

                        #self.add_spectrum(spectrum,spectrum_type,precursor_mz)
                        peaklist = {
                            'm/z array': spectrum['m/z array'],
                            'intensity array': spectrum['intensity array']
                        }

                        #### Check for zero length and very sparse spectra
                        if len(spectrum['m/z array']) == 0:
                            stats['n_length_zero_spectra'] += 1
                        if len(spectrum['m/z array']) < 10:
                            stats['n_length_lt10_spectra'] += 1

                        #spectra.append([stats,precursor_mz,peaklist])
                        self.add_spectrum([stats,precursor_mz,peaklist])

                        # If the user requested writing of a fragmentation_type_file, record that information
                        if write_fragmentation_type_file is not None:
                            nativeId = spectrum['id']
                            scan_number = -1
                            match = re.search(r'scan=(\d+)',nativeId)
                            if match:
                                scan_number = match.group(1)
                            scan_fragmentation_list.append(f"{scan_number}\t{stats['fragmentation_tag']}")

                    #### Update counters and print progress
                    stats['n_spectra'] += 1
                    if self.verbose >= 1:
                        if stats['n_spectra']/500 == int(stats['n_spectra']/500):
                            if not progress_intro:
                                #eprint("INFO: Reading spectra.. ", end='')
                                progress_intro = True
                            #eprint(f"{stats['n_spectra']}.. ", end='', flush=True)
                            eprint(".", end='', flush=True)
            #except:
            else:
                self.log_event('ERROR','MzMLCorrupt',f"Pyteomics threw an error reading mzML file! File may be corrupt. Check file '{self.mzml_file}'")

        infile.close()
        #if self.verbose >= 1: eprint("")

        # If the user requested writing of a fragmentation_type_file, write it out
        if write_fragmentation_type_file is not None:
            filename = self.mzml_file
            filename = re.sub(r'\.gz','',filename)
            filename = re.sub(r'\.mzML','',filename)
            filename += '.fragmentation_types.tsv'
            eprint(f"\nINFO: Writing fragmentation type file {filename}", end='', flush=True)
            with open(filename,'w') as outfile:
                if stats['fragmentation_type'] != 'multiple':
                    scan_fragmentation = scan_fragmentation_list[0]
                    scan_fragmentation = re.sub(r'^\d+','*',scan_fragmentation)
                    outfile.write(scan_fragmentation+'\n')
                else:
                    for scan_fragmentation in scan_fragmentation_list:
                        outfile.write(scan_fragmentation+'\n')

        #### If there are no spectra that were saved, then we're done with this file
        if stats['n_ms2_spectra'] == 0:
            self.log_event('ERROR','NoMS2Scans',f"This mzML file has no MS2 scans. Check file '{self.mzml_file}'")

        #### Try to distinguish DDA vs DIA
        if 'isolation_window_full_widths' in stats:
            smallest_window = 999999
            largest_window = 0
            for window_size in stats['isolation_window_full_widths']:
                window_size = float(window_size)
                if  window_size < smallest_window:
                    smallest_window = window_size
                if window_size > largest_window:
                    largest_window = window_size
            if largest_window <= 3.0:
                stats['acquisition_type'] = 'DDA'
            elif largest_window >= 15.0:
                stats['acquisition_type'] = 'DIA'
            else:
                stats['acquisition_type'] = 'ambiguous'
        else:
            stats['acquisition_type'] = 'unknown'


        #### Now that we've read anything, try to process the data multithreaded
        #n_threads = 8
        #if self.verbose >= 1: eprint(f"INFO: processing {len(spectra)} spectra multithreaded with {n_threads} threads")
        #pool = ThreadPool(n_threads)
        #results = pool.imap_unordered(self.add_spectrum, spectra)
        #results = pool.map(self.add_spectrum, spectra)
        #pool.close()
        #pool.join()
        #if self.verbose >= 1: eprint(f"INFO: Done.")

        #### Write the composite spectrum to a file
        #with open('zzcomposite_spectrum.pickle','wb') as outfile:
        #    pickle.dump(self.composite,outfile)

        #### Print final timing information
        t1 = timeit.default_timer()
        print(f"\nINFO: Read {stats['n_spectra']} spectra from {self.mzml_file} in {t1-t0:.2f} sec ({stats['n_spectra']/(t1-t0):.2f} spectra per sec)", end='', flush=True)


    ####################################################################################################
    #### Record the isolation window information
    def record_isolation_window_stats(self, spectrum, stats):
        isolation_window_target_mz = None
        isolation_window_lower_offset = None
        isolation_window_upper_offset = None
        try:
            isolation_window_target_mz = spectrum['precursorList']['precursor'][0]['isolationWindow']['isolation window target m/z']
            isolation_window_lower_offset = spectrum['precursorList']['precursor'][0]['isolationWindow']['isolation window lower offset']
            isolation_window_upper_offset = spectrum['precursorList']['precursor'][0]['isolationWindow']['isolation window upper offset']
        except:
            # Cannot get the isolation window information. oh well
            pass
        if 'isolation_window_full_widths' not in stats:
            stats['isolation_window_full_widths'] = {}
        if isolation_window_lower_offset is not None and isolation_window_upper_offset is not None:
            full_width = isolation_window_lower_offset + isolation_window_upper_offset
            if full_width not in stats['isolation_window_full_widths']:
                stats['isolation_window_full_widths'][full_width] = 0
            stats['isolation_window_full_widths'][full_width] += 1


    ####################################################################################################
    #### Parse the filter string
    def parse_filter_string(self,filter_string,stats):

        fragmentation_tag = '??'

        mass_accuracy = '??'
        match = re.search(r'^(\S+)',filter_string)
        if match.group(0) == 'FTMS' or match.group(0) == 'ASTMS':
            mass_accuracy = 'HR'
        elif match.group(0) == 'ITMS':
            mass_accuracy = 'LR'
        else:
            self.log_event('ERROR','UnrecognizedDetector',f"Unrecognized detector '{match.group(0)}' in filter string {filter_string}")
            return

        ms_level = 0
        match = re.search(r' ms ',filter_string)
        if match:
            ms_level = 1
        else:
            match = re.search(r' ms(\d) ',filter_string)
            if match:
                ms_level = int(match.group(1))
            else:
                self.log_event('ERROR','UnrecognizedMSLevel',f"Unrecognized MS level in filter string {filter_string}")
                return

        # See if there's fragmentation of a known type
        have_cid = 0
        have_etd = 0
        have_hcd = 0
        have_fragmentation = 0
        match = re.search(r'@hcd',filter_string)
        if match: have_hcd = 1
        match = re.search(r'@cid',filter_string)
        if match: have_cid = 1
        match = re.search(r'@etd',filter_string)
        if match: have_etd = 1
        match = re.search(r'@',filter_string)
        if match: have_fragmentation = 1
        dissociation_sum = have_cid + have_etd + have_hcd
        if have_fragmentation > dissociation_sum:
            self.log_event('ERROR','UnrecognizedFragmentation',f"Unrecognized string after @ in filter string '{filter_string}'")
            return

        #### If this is an MS1 scan, learn what we can from it
        if ms_level == 0:
            if 'n_ms0_spectra' not in stats:
                stats['n_ms0_spectra'] = 0
            stats['n_ms0_spectra'] += 1
            self.log_event('ERROR','UnknownMSLevel',f"Unable to determine MS level in filter string '{filter_string}'")
            return

        #### If this is an MS1 scan, learn what we can from it
        if ms_level == 1:
            stats['n_ms1_spectra'] += 1
            spectrum_type = 'MS1'
            if mass_accuracy == 'HR':
                if stats['high_accuracy_precursors'] == 'unknown':
                    stats['high_accuracy_precursors'] = 'true'
                elif stats['high_accuracy_precursors'] == 'true' or stats['high_accuracy_precursors'] == 'multiple':
                    pass
                elif stats['high_accuracy_precursors'] == 'false':
                    stats['high_accuracy_precursors'] = 'multiple'
                else:
                    self.log_event('ERROR','InternalStateError',f"high_accuracy_precursors has a strange state '{stats['high_accuracy_precursors']}'")
                    return
            elif mass_accuracy == 'LR':
                if stats['high_accuracy_precursors'] == 'unknown':
                    stats['high_accuracy_precursors'] = 'false'
                elif stats['high_accuracy_precursors'] == 'false' or stats['high_accuracy_precursors'] == 'multiple':
                    pass
                elif stats['high_accuracy_precursors'] == 'true':
                    stats['high_accuracy_precursors'] = 'multiple'
                else:
                    self.log_event('ERROR','InternalStateError',f"high_accuracy_precursors has a strange state '{stats['high_accuracy_precursors']}'")
                    return
            else:
                self.log_event('ERROR','UnknownPrecursorScanType',f"Unknown precursor scan type '{match.group(0)}'")
                return

        #### Else it's an MSn (n>1) scan so learn what we can from that
        elif ms_level == 2:
            dissociation_sum = have_cid + have_etd + have_hcd
            stats['n_ms2_spectra'] += 1
            if dissociation_sum == 1:
                if have_hcd:
                    stats[f"n_{mass_accuracy}_HCD_spectra"] += 1
                    spectrum_type = f"{mass_accuracy}_HCD"
                    fragmentation_tag = f"{mass_accuracy} HCD"
                elif have_cid:
                    stats[f"n_{mass_accuracy}_IT_CID_spectra"] += 1
                    spectrum_type = f"{mass_accuracy}_IT_CID"
                    fragmentation_tag = f"{mass_accuracy} IT CID"
                elif have_etd:
                    stats[f"n_{mass_accuracy}_IT_ETD_spectra"] += 1
                    spectrum_type = f"{mass_accuracy}_IT_ETD"
                    fragmentation_tag = f"{mass_accuracy} IT ETD"
                else:
                    self.log_event('ERROR','UnrecognizedFragmentation',f"Did not find @hcd, @cid, @etd in filter string '{filter_string}'")
                    return

            elif dissociation_sum == 2:
                if have_etd and have_hcd:
                    stats[f"n_{mass_accuracy}_EThcD_spectra"] += 1
                    spectrum_type = f"{mass_accuracy}_EThcD"
                    fragmentation_tag = f"{mass_accuracy} EThcD"
                elif have_etd and have_cid:
                    stats[f"n_{mass_accuracy}_ETciD_spectra"] += 1
                    spectrum_type = f"{mass_accuracy}_ETciD"
                    fragmentation_tag = f"{mass_accuracy} ETciD"
                else:
                    self.log_event('ERROR','UnrecognizedFragmentation',f"Did not find known fragmentation combination in filter string '{filter_string}'")
                    return

            else:
                self.log_event('ERROR','CantParseFilterStr',f"Unable to determine dissociation type in filter string '{filter_string}'")
                return

            #### Record the fragmentation type for this run
            if spectrum_type != stats['fragmentation_type']:
                if stats['fragmentation_type'] == 'unknown':
                    stats['fragmentation_type'] = spectrum_type
                elif stats['fragmentation_type'] == 'multiple':
                    pass
                else:
                    stats['fragmentation_type'] = 'multiple'
                    self.log_event('ERROR','MultipleFragTypes',f"There are multiple fragmentation types in this MS run. Split them.")


        # If we have ms_level > 2, then make a note, but this is uncharted waters
        else:
            if 'n_ms3+_spectra' not in stats:
                stats['n_ms3+_spectra'] = 0
            stats['n_ms3+_spectra'] += 1

        # Store the fragmentation_tag for use by the caller
        stats['fragmentation_tag'] = fragmentation_tag



    ####################################################################################################
    #### Add spectrum
    #def add_spectrum(self,spectrum,spectrum_type,precursor_mz):
    def add_spectrum(self,params):

        stats, precursor_mz, peaklist = params
        spectrum_type = stats['fragmentation_type']

        if 'n_spectra_examined' not in self.metadata['files'][self.mzml_file]['spectra_stats']:
            self.metadata['files'][self.mzml_file]['spectra_stats']['n_spectra_examined'] = 0
        self.metadata['files'][self.mzml_file]['spectra_stats']['n_spectra_examined'] += 1

        destination = f"lowend_{spectrum_type}"
        #destination2 = f"neutral_loss_{spectrum_type}"

        if destination not in self.composite:
            if spectrum_type == 'HR_HCD':
                #print(f"INFO: Creating a composite spectrum {destination}")
                minimum = 100
                maximum = 400
                binsize = 0.0002
                array_size = int( (maximum - minimum ) / binsize ) + 1
                self.composite[destination] = { 'minimum': minimum, 'maximum': maximum, 'binsize': binsize }
                self.composite[destination]['intensities'] = numpy.zeros(array_size,dtype=numpy.float32)
                self.composite[destination]['n_peaks'] = numpy.zeros(array_size,dtype=numpy.int32)

                #print(f"INFO: Creating a composite spectrum {destination2}")
                # minimum = 0
                # maximum = 165
                # binsize = 0.001
                # array_size = int( (maximum - minimum ) / binsize ) + 1
                # self.composite[destination2] = { 'minimum': minimum, 'maximum': maximum, 'binsize': binsize }
                # self.composite[destination2]['intensities'] = numpy.zeros(array_size,dtype=numpy.float32)
                # self.composite[destination2]['n_peaks'] = numpy.zeros(array_size,dtype=numpy.int32)

            elif spectrum_type == 'LR_IT_CID':
                #print(f"INFO: Creating a composite spectrum {destination}")
                minimum = 100
                maximum = 460
                binsize = 0.05
                array_size = int( (maximum - minimum ) / binsize ) + 1
                self.composite[destination] = { 'minimum': minimum, 'maximum': maximum, 'binsize': binsize }
                self.composite[destination]['intensities'] = numpy.zeros(array_size,dtype=numpy.float32)
                self.composite[destination]['n_peaks'] = numpy.zeros(array_size,dtype=numpy.int32)

            elif spectrum_type == 'LR_IT_ETD':
                #print(f"INFO: Creating a composite spectrum {destination}")
                minimum = 100
                maximum = 400
                binsize = 0.05
                array_size = int( (maximum - minimum ) / binsize ) + 1
                self.composite[destination] = { 'minimum': minimum, 'maximum': maximum, 'binsize': binsize }
                self.composite[destination]['intensities'] = numpy.zeros(array_size,dtype=numpy.float32)
                self.composite[destination]['n_peaks'] = numpy.zeros(array_size,dtype=numpy.int32)

            else:
                #print(f"ERROR: Unrecognized spectrum type {spectrum_type}")
                return

        #### Convert the peak lists to numpy arrays
        intensity_array = numpy.asarray(peaklist['intensity array'])
        mz_array = numpy.asarray(peaklist['m/z array'])

        #### Limit the numpy arrays to the region we're interested in
        intensity_array = intensity_array[ ( mz_array > self.composite[destination]['minimum'] ) & ( mz_array < self.composite[destination]['maximum'] ) ]
        mz_array = mz_array[ ( mz_array > self.composite[destination]['minimum'] ) & ( mz_array < self.composite[destination]['maximum'] ) ]

        #### Compute their bin locations and store n_peaks and intensities
        bin_array = (( mz_array - self.composite[destination]['minimum'] ) / self.composite[destination]['binsize']).astype(int)
        self.composite[destination]['n_peaks'][bin_array] += 1
        self.composite[destination]['intensities'][bin_array] += intensity_array

        #### The stuff below was trying to compute neutral losses. It works, but it's too slow. Need a Cython implementation I guess

        # sorted_mz_intensity = sorted(mz_intensity, key=lambda pair: pair[2], reverse=True)
        # length = 30
        # if len(mz_intensity) < 30:
            # length = len(mz_intensity)
        # clipped_mz_intensity = sorted_mz_intensity[0:(length-1)]
        # mz_intensity = sorted(clipped_mz_intensity, key=lambda pair: pair[1], reverse=False)
        # i = 0
        # while i < length-1:
            # mz_intensity[i][0] = i
            # i += 1
        # sorted_mz_intensity = sorted(mz_intensity, key=lambda pair: pair[2], reverse=True)


        # imajor_peak = 0
        # while imajor_peak < 20 and imajor_peak < len(mz_intensity):
            # ipeak,mz,major_intensity = sorted_mz_intensity[imajor_peak]
            # #print(ipeak,mz,major_intensity)
            # if major_intensity == 0.0:
                # major_intensity = 1.0
            # imz = mz
            # while ipeak > 0 and mz - imz < self.composite[destination2]['maximum'] and imz > 132 and abs(imz - precursor_mz) > 5:
                # bin = int( ( mz - imz ) / self.composite[destination2]['binsize'])
                # #print("  - ",ipeak,imz,bin,intensity)
                # self.composite[destination2]['n_peaks'][bin] += 1
                # self.composite[destination2]['intensities'][bin] += intensity
                # ipeak -= 1
                # imz = mz_intensity[ipeak][1]
                # intensity = mz_intensity[ipeak][2]
            # imajor_peak += 1


    ####################################################################################################
    #### Read header
    #### Open the mzML file and read line by line into a text buffer that we will XML parse
    def read_header(self):

        #### If the mzML is gzipped, then open with zlib, else a plain open
        match = re.search(r'\.gz$',self.mzml_file)
        if match:
            infile = gzip.open(self.mzml_file)
        else:
            infile = open(self.mzml_file)

        #### set up a text buffer to hold the mzML header
        buffer = ''
        counter = 0

        #### Keep a dict of random recognized things
        recognized_things = {}

        #### Read line by line
        for line in infile:

            if not isinstance(line, str):
                line = str(line, 'utf-8', 'ignore')

            #### Completely skip the <indexedmzML> tag if present
            if '<indexedmzML ' in line:
                continue

            #### Look for first tag after the header and end when found
            if '<run ' in line:
                break

            #### Look for some known artificts that are useful to record
            if 'softwareRef="tdf2mzml"' in line:
                recognized_things['converted with tdf2mzml'] = True
                recognized_things['likely a timsTOF'] = True

            #### Update the buffer and counter
            if counter > 0:
                buffer += line
            counter += 1

        #### Close file and process the XML in the buffer
        infile.close()

        #### Finish the XML by closing the tags
        buffer += '  </mzML>\n'

        #### Get the root of the XML and the namespace
        xmlroot = etree.fromstring(buffer)
        namespace = xmlroot.nsmap
        #print(namespace)
        if None in namespace:
            namespace = '{'+namespace[None]+'}'
        else:
            namespace = ''

        #### Create a reference of instruments we know
        instrument_by_category = {
            'pureHCD': [
                'MS:1000649|Exactive',
                'MS:1001911|Q Exactive',
                'MS:1002526|Exactive Plus',
                'MS:1002634|Q Exactive Plus',
                'MS:1002523|Q Exactive HF',
                'MS:1002877|Q Exactive HF-X',
                'MS:1003378|Orbitrap Astral',
                'MS:1003442|Orbitrap Astral Zoom'
            ],
            'ion_trap': [
                'MS:1000447|LTQ',
                'MS:1000638|LTQ XL ETD',
                'MS:1000854|LTQ XL',
                'MS:1000855|LTQ Velos',
                'MS:1000856|LTQ Velos ETD',
                'MS:1000167|LCQ Advantage',
                'MS:1000168|LCQ Classic',
                'MS:1000169|LCQ Deca XP Plus',
                'MS:1000554|LCQ Deca',
                'MS:1000578|LCQ Fleet'
            ],
            'variable': [ 
                'MS:1000448|LTQ FT', 
                'MS:1000557|LTQ FT Ultra', 
                'MS:1000449|LTQ Orbitrap',
                'MS:1000555|LTQ Orbitrap Discovery', 
                'MS:1000556|LTQ Orbitrap XL',
                'MS:1000639|LTQ Orbitrap XL ETD',
                'MS:1001910|LTQ Orbitrap Elite', 
                'MS:1001742|LTQ Orbitrap Velos', 
                'MS:1002835|LTQ Orbitrap Classic', 
                'MS:1002416|Orbitrap Fusion', 
                'MS:1002417|Orbitrap Fusion ETD', 
                'MS:1002732|Orbitrap Fusion Lumos',
                'MS:1003028|Orbitrap Exploris 480',
                'MS:1003029|Orbitrap Eclipse',
                'MS:1003356|Orbitrap Ascend',
                'MS:1000031|instrument model',
                'MS:1000483|Thermo Fisher Scientific instrument model'
            ],
            'QTOF': [
                'MS:1000126|Waters instrument model',
                'MS:1000122|Bruker Daltonics instrument model',
                'MS:1000121|AB SCIEX instrument model'
            ]
        }

        #### Some special cases to look out for
        special_cases = {
            'MS:1000566': {
                'exact_name': 'ISB mzXML format',
                'rank': '5',
                'category': 'unknown',
                'final_name': 'Conversion to mzML from mzXML from unknown instrument' },
            'MS:1000562': {
                'exact_name': 'ABI WIFF format',
                'rank': '2',
                'category': 'QTOF',
                'final_name': 'SCIEX instrument model' },
            'MS:1000551': {
                'exact_name': 'Analyst',
                'rank': '3',
                'category': 'QTOF',
                'final_name': 'SCIEX instrument model' }
        }

        #### Restructure it into a dict by PSI-MS identifier
        instrument_attributes = {}
        for instrument_category in instrument_by_category:
            for instrument_string in instrument_by_category[instrument_category]:
                accession,name = instrument_string.split('|')
                instrument_attributes[accession] = { 'category': instrument_category, 'accession': accession, 'name': name }

        #### Get all the CV params in the header and look for ones we know about
        cv_params = xmlroot.findall(f'.//{namespace}cvParam')
        found_instrument = 0
        model_data = None
        for cv_param in cv_params:
            accession = cv_param.get('accession')
            if accession in instrument_attributes:
                #### Store the attributes about this instrument model
                model_data = {
                    'accession': accession,
                    'name': instrument_attributes[accession]['name'],
                    'category': instrument_attributes[accession]['category'],
                    'rank': '1'
                }
                if 'likely a timsTOF' in recognized_things:
                    model_data['inferred_name'] = 'timsTOF'
                self.metadata['files'][self.mzml_file]['instrument_model'] = model_data
                found_instrument = 1

            #### Handle some special cases
            if accession in special_cases:
                if model_data is None or special_cases[accession]['rank'] < model_data['rank']:
                    model_data = {
                        'accession': accession,
                        'name': special_cases[accession]['final_name'],
                        'category': special_cases[accession]['category'],
                        'rank': special_cases[accession]['rank']
                    }
                    self.metadata['files'][self.mzml_file]['instrument_model'] = model_data
                    found_instrument = 1

        #### If none are an instrument we know about about, ask for help
        if not found_instrument:
            self.log_event('ERROR','UnrecogInstr',f"Did not recognize the instrument. Please teach me about this instrument.")
            model_data = {
                'accession': None,
                'name': 'unknown',
                'category': 'unknown'
            }
            self.metadata['files'][self.mzml_file]['instrument_model'] = model_data
            return


        #### Read and store the referenceable param groups
        referenceable_param_group_list = xmlroot.findall(f'.//{namespace}referenceableParamGroup')
        for referenceable_param_group in referenceable_param_group_list:
            group_id = referenceable_param_group.get('id')
            self.referenceable_param_group_list[group_id] = {}
            for subelement in list(referenceable_param_group):
                name = subelement.get('name')
                value = subelement.get('value')
                self.referenceable_param_group_list[group_id][name] = value



    ####################################################################################################
    #### Assess composite spectra
    def assess_composite_spectra(self):
        #with open('zzcomposite_spectrum.pickle','rb') as infile:
        #    spec = pickle.load(infile)
        spec = self.composite

        supported_composite_type_list = [ 'lowend_HR_HCD', 'lowend_LR_IT_CID' ]

        composite_type = None
        for supported_composite_type in supported_composite_type_list:
            if supported_composite_type in spec:
                composite_type = supported_composite_type

        if composite_type is None:
            self.log_event('WARNING','UnknownFragmentation',f"Not able to determine more about these spectra yet.")
            return

        minimum = spec[composite_type]['minimum']
        maximum = spec[composite_type]['maximum']
        binsize = spec[composite_type]['binsize']
        spec[composite_type]['mz'] = numpy.arange(minimum, maximum + binsize, binsize)

        ROIs = {
            'TMT6_126': { 'type': 'TMT', 'mz': 126.127725, 'initial_window': 0.01 },
            'TMT6_127': { 'type': 'TMT', 'mz': 127.124760, 'initial_window': 0.01 },
            'TMT6_128': { 'type': 'TMT', 'mz': 128.134433, 'initial_window': 0.01 },
            'TMT6_129': { 'type': 'TMT', 'mz': 129.131468, 'initial_window': 0.01 },
            'TMT6_130': { 'type': 'TMT', 'mz': 130.141141, 'initial_window': 0.01 },
            'TMT6_131': { 'type': 'TMT', 'mz': 131.138176, 'initial_window': 0.01 },
            'TMT6plex': { 'type': 'TMT', 'mz': 230.1702, 'initial_window': 0.01 },
            'TMTpro': { 'type': 'TMTpro', 'mz': 305.2144, 'initial_window': 0.01 },
            'TMTpro+H2O': { 'type': 'TMTpro', 'mz': 323.22499, 'initial_window': 0.01 },
            'iTRAQ_114': { 'type': 'iTRAQ', 'mz': 114.11068, 'initial_window': 0.01 },
            'iTRAQ_115': { 'type': 'iTRAQ', 'mz': 115.107715, 'initial_window': 0.01 },
            'iTRAQ_116': { 'type': 'iTRAQ', 'mz': 116.111069, 'initial_window': 0.01 },
            'iTRAQ_117': { 'type': 'iTRAQ', 'mz': 117.114424, 'initial_window': 0.01 },
            'iTRAQ4_nterm': { 'type': 'iTRAQ4', 'mz': 145.109, 'initial_window': 0.01 },
            'iTRAQ8_118': { 'type': 'iTRAQ8', 'mz': 118.111459, 'initial_window': 0.01 },
            'iTRAQ8_119': { 'type': 'iTRAQ8', 'mz': 119.114814, 'initial_window': 0.01 },
            'iTRAQ8_121': { 'type': 'iTRAQ8', 'mz': 121.121524, 'initial_window': 0.01 },
            'iTRAQ8_113': { 'type': 'iTRAQ8', 'mz': 113.107325, 'initial_window': 0.01 },
        }

        #### What should we look at for ion trap data?
        if composite_type == 'lowend_LR_IT_CID':
            ROIs = {
                'TMT6plex': { 'type': 'TMT', 'mz': 230.1702, 'initial_window': 1.0 },
                'TMT6_y1K': { 'type': 'TMT', 'mz': 376.2757, 'initial_window': 1.0 },
                'TMTpro': { 'type': 'TMTpro', 'mz': 305.2144, 'initial_window': 0.01 },
                'TMTpro+H2O': { 'type': 'TMTpro', 'mz': 323.22499, 'initial_window': 0.01 },
                'iTRAQ4_y1K': { 'type': 'iTRAQ4', 'mz': 376.2757, 'initial_window': 1.0 },
                'iTRAQ8_y1K': { 'type': 'iTRAQ8', 'mz': 451.3118, 'initial_window': 1.0 },
            }


        for ROI in ROIs:
            #print(f"INFO: Looking for {ROI} at {ROIs[ROI]['mz']}")
            #center = ROIs[ROI]['mz']
            #range = ROIs[ROI]['initial_window']
            #first_bin = int((center - range/2.0 - minimum) / binsize)
            #last_bin = int((center + range/2.0 - minimum) / binsize)

            #### Look for the largest peak
            peak = self.find_peak(spec,ROIs,ROI,composite_type)
            ROIs[ROI]['peak'] = peak
            #print(peak)

        self.metadata['files'][self.mzml_file]['ROIs'] = ROIs


    ####################################################################################################
    #### Peak finding routine
    def find_peak(self,spec,ROIs,ROI,composite_type):
        minimum = spec[composite_type]['minimum']
        #maximum = spec[composite_type]['maximum']
        binsize = spec[composite_type]['binsize']
        center = ROIs[ROI]['mz']
        range = ROIs[ROI]['initial_window']
        first_bin = int((center - range/2.0 - minimum) / binsize)
        last_bin = int((center + range/2.0 - minimum) / binsize)

        peak = { 'mode_bin': { 'ibin': 0, 'mz': 0, 'intensity': 0, 'n_spectra': 0 } }

        #### Find the tallest peak in the window
        ibin = first_bin
        while ibin < last_bin:
            if spec[composite_type]['intensities'][ibin] > peak['mode_bin']['intensity']:
                peak['mode_bin']['ibin'] = ibin
                peak['mode_bin']['mz'] = float(spec[composite_type]['mz'][ibin])
                peak['mode_bin']['intensity'] = float(spec[composite_type]['intensities'][ibin])
                peak['mode_bin']['n_spectra'] = int(spec[composite_type]['n_peaks'][ibin])
            ibin += 1

        #### If there were 0 peaks found, return a verdict now
        if peak['mode_bin']['ibin'] == 0:
            peak['assessment'] = { 'is_found': False, 'fraction': 0.0 }
            return(peak)

        #### Grow the extent to get most of the signal
        ibin = peak['mode_bin']['ibin']
        iextent = 1
        done = 0
        prev_n_spectra = peak['mode_bin']['n_spectra']
        peak['extended'] = { 'extent': 0, 'intensity': float(peak['mode_bin']['intensity']), 'n_spectra': int(peak['mode_bin']['n_spectra']) }
        #print(spec[composite_type]['n_peaks'][ibin-10:ibin+10])
        while not done:
            prev_intensity = peak['extended']['intensity']
            prev_n_spectra = peak['extended']['n_spectra']
            new_intensity = prev_intensity + spec[composite_type]['intensities'][ibin-iextent] + spec[composite_type]['intensities'][ibin+iextent]
            new_n_spectra = prev_n_spectra + spec[composite_type]['n_peaks'][ibin-iextent] + spec[composite_type]['n_peaks'][ibin+iextent]
            #print(new_intensity/prev_intensity, new_n_spectra/prev_n_spectra)
            peak['extended'] = { 'extent': iextent, 'intensity': float(new_intensity), 'n_spectra': int(new_n_spectra) }
            if new_n_spectra/prev_n_spectra < 1.02:
                #print('Extent reached by n_spectra')
                done = 1
            if iextent > 15:
                #print('Extent reached by max extent')
                done = 1
            iextent += 1

        if peak['extended']['n_spectra'] > 100:
            extent = peak['extended']['extent'] * 2
            x = spec[composite_type]['mz'][ibin-extent:ibin+extent]
            y = spec[composite_type]['intensities'][ibin-extent:ibin+extent]

            n = len(x)
            center = int(n/2)
            binsize = x[center]-x[center-1]

            try:
            #if 1:
                popt,pcov = curve_fit(gaussian_function,x,y,p0=[y[center],x[center],binsize])
                peak['fit'] = { 'mz': popt[1], 'intensity': popt[0], 'sigma': popt[2], 'delta_mz': popt[1]-ROIs[ROI]['mz'], 'delta_ppm': (popt[1]-ROIs[ROI]['mz'])/ROIs[ROI]['mz']*1e6 }
                peak['assessment'] = { 'is_found': True, 'fraction': 0.0, 'comment': 'Peak found and fit' }
            except:
            #else:
                peak['assessment'] = { 'is_found': False, 'fraction': 0.0, 'comment': 'Gaussian fit failed to converge' }

            if 0:
                plt.step(x+binsize/2.0,y,'b+:')
                plt.plot(x,gaussian_function(x,*popt),'ro:')
                title = "Fit results: mz = %.4f, sigma = %.4f" % (popt[1], popt[2])
                plt.title(title)
                plt.show()

        else:
            peak['assessment'] = { 'is_found': False, 'fraction': 0.0, 'comment': 'Too few peaks found in ROI' }

        return(peak)


    ####################################################################################################
    #### Assess Regions of Interest to make calls
    def assess_ROIs(self):
        results = { 'labeling': { 'scores': { 'TMT': 0, 'TMT6': 0, 'TMT10': 0, 'TMTpro': 0, 'iTRAQ': 0, 'iTRAQ4': 0, 'iTRAQ8': 0 } } }

        #### Determine what the denominator of MS2 spectra should be
        n_ms2_spectra = self.metadata['files'][self.mzml_file]['spectra_stats']['n_ms2_spectra']
        if ( 'n_HCD_spectra' in self.metadata['files'][self.mzml_file]['spectra_stats'] and
                self.metadata['files'][self.mzml_file]['spectra_stats']['n_HCD_spectra'] > 0 and 
                self.metadata['files'][self.mzml_file]['spectra_stats']['n_HCD_spectra'] <
                self.metadata['files'][self.mzml_file]['spectra_stats']['n_ms2_spectra'] ):
            n_ms2_spectra = self.metadata['files'][self.mzml_file]['spectra_stats']['n_HCD_spectra']

        #### Determine the fragmentation_type
        results['fragmentation_type'] = self.metadata['files'][self.mzml_file]['spectra_stats']['fragmentation_type']
        self.metadata['files'][self.mzml_file]['summary'] = results

        #### If no ROIs were computed, cannot continue
        if 'ROIs' not in self.metadata['files'][self.mzml_file]:
            return

        for ROI in self.metadata['files'][self.mzml_file]['ROIs']:
            ROIobj = self.metadata['files'][self.mzml_file]['ROIs'][ROI]
            if ROIobj['peak']['assessment']['is_found']:
                type = ROIobj['type']
                n_spectra = ROIobj['peak']['extended']['n_spectra']
                ROIobj['peak']['assessment']['fraction'] = n_spectra / n_ms2_spectra
                results['labeling']['scores'][type] += ROIobj['peak']['assessment']['fraction']

        #### Make the call for TMT or iTRAQ
        if results['labeling']['scores']['TMT'] > results['labeling']['scores']['iTRAQ']:
            if results['labeling']['scores']['TMT'] > 2:
                if results['labeling']['scores']['TMTpro'] > 0.7:
                    results['labeling']['call'] = 'TMTpro'
                else:
                    results['labeling']['call'] = 'TMT'
            elif results['labeling']['scores']['TMT'] < 1:
                results['labeling']['call'] = 'none'
            else:
                results['labeling']['call'] = 'ambiguous'
        else:
            if results['labeling']['scores']['iTRAQ'] > 1:
                if results['labeling']['scores']['iTRAQ4'] > results['labeling']['scores']['iTRAQ8']:
                    results['labeling']['call'] = 'iTRAQ4'
                else:
                    results['labeling']['call'] = 'iTRAQ8'
            elif results['labeling']['scores']['iTRAQ'] < 0.5:
                results['labeling']['call'] = 'none'
            else:
                results['labeling']['call'] = 'ambiguous'



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
#### Gaussian function used for curve fitting
def gaussian_function(x,a,x0,sigma):
    return a*numpy.exp(-(x-x0)**2/(2*sigma**2))


####################################################################################################
#### For command-line usage
def main():

    argparser = argparse.ArgumentParser(description='Creates an index for an MSP spectral library file')
    argparser.add_argument('--use_cache', action='store', help='Set to true to use the cached file instead of regenerating')
    argparser.add_argument('--refresh', action='count', default=0, help='If set, existing metadata for a file will be overwritten rather than skipping the file')
    argparser.add_argument('--verbose', action='count', help='If set, print more information about ongoing processing' )
    argparser.add_argument('--version', action='version', version='%(prog)s 0.5')
    argparser.add_argument('--outpath', default='./', help='outpath to store the metadata file. Default is ./')
    argparser.add_argument('--inpath', type=str, help='input directory containing the .mzML files')
    params = argparser.parse_args()

    #### Set verbose
    verbose = params.verbose
    if verbose is None: verbose = 1

    #### Loop over all the files to ensure that they are really there before starting work
    print(f'params.inpath: {params.inpath}')
    if os.path.isfile(params.inpath):
        files = [params.inpath]
    else:
        try:
            files = glob.glob(os.path.join(params.inpath, '*.mzML'))
            print(files)
            for file in files:
                print(f"Checking file: {file}")
                if not os.path.isfile(file):
                    print(f"ERROR: File '{file}' not found or not a file")
                    return
        except Exception as e:
            print(f"ERROR: Could not read files from '{params.inpath}': {e}")
            return

    #### Load the current metadata file in order to update it
    study = MetadataHandler(verbose=verbose, outpath=params.outpath)
    study.read_or_create()

    #### Loop over all the files processing them
    assessor = None  # Initialize to None - safe default
    for file in files:
        print(f'Processings {file}')

        #### If this file is already in the metadata store, purge it and generate new
        if file in study.metadata['files']:
            if params.refresh is not None and params.refresh > 0:
                study.metadata['files'][file] = None
            else:
                if verbose >= 1: eprint(f"INFO: Already have results for '{file}'. Skipping..")
                continue

        #### Assess the mzML file
        assessor = MzMLAssessor(file, metadata=study.metadata, verbose=verbose)
        assessor.read_header()
        if not params.use_cache:
            assessor.read_spectra()
        assessor.assess_composite_spectra()
        print(assessor.metadata['state']['status'])
        if assessor.metadata['state']['status'] != 'ERROR':
            assessor.assess_ROIs()

    #### Infer parameters based on the latest data
    if assessor is not None and assessor.metadata['state']['status'] != 'ERROR':
        study.infer_search_criteria()
    elif assessor is None:
        eprint(f"WARNING: No mzML files found in {params.inpath}. Skipping parameter inference.")

    #### Write out our state of mind
    study.store()


#### For command line usage
if __name__ == "__main__": main()
