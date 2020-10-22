#!/usr/bin/env python3

"""Feature Wishlist
Top priority:
Internal contig name system (see prependUniqueIDs in cactus/src/cactus/pipeline/cactus_workflow.py, line 465)
Called in line 529:
    renamedInputSeqDir = fileStore.getLocalTempDir()
    uniqueFas = prependUniqueIDs(sequences, renamedInputSeqDir)
    uniqueFaIDs = [fileStore.writeGlobalFile(seq, cleanup=True) for seq in uniqueFas]

    I'm currently calling prependUniqueIDs outside of the workflow/fileStore. I should
        check to make sure that Cactus also ultimately exports the uniqueID files,
        like I'm doing. Otherwise, I should delete the prepended IDs before finishing 
        the pipeline.



Implement options.pathOverrides
Implement "Progressive Cactus Options" (see cactus_blast ArgumentParser)
    This includes s3 compatibility, I think?
logger.info timer (see line 91 of cactus_blast)

    """


from toil.common import Toil
from toil.job import Job

import subprocess
import os
from argparse import ArgumentParser
import collections as col

from cactus.reference_align import paf_to_lastz
from cactus.reference_align import fasta_preprocessing
from cactus.reference_align import apply_dipcall_bed_filter

from cactus.shared.common import makeURL
from cactus.progressive.seqFile import SeqFile
from cactus.pipeline.cactus_workflow import prependUniqueIDs

## utilitary fxns:

def variation_length(lastz_cig_list):
    # 0, 2, 4,... are the type of variation.
    # 1, 3, 5,... are the length of the variation of that type.
    # there should be an even number of entries in the cig list: pairs of type, value.
    var_len = 0
    for i in range(0, len(lastz_cig_list), 2):
        print(i, lastz_cig_list[i], lastz_cig_list[i+1])
        if lastz_cig_list[i] in "IDM":
            var_len += int(lastz_cig_list[i+1])
    return var_len

def unpack_promise(job, iterable, i):
    """
    passed an iterable and a location i, returns ith item.
    """
    return iterable[i]

def consolidate_mappings(job, mapping_files):
    """
    Warning: discards headers of all mapping files.
    Given a list of mapping files, consolidates the contents (not counting headers) into a
    single file.
    """
    consolidated_mappings = job.fileStore.getLocalTempFile()
    with open(consolidated_mappings,"w") as outfile:
        for mapping_file in mapping_files.values():
            with open(job.fileStore.readGlobalFile(mapping_file)) as inf:
                for line in inf:
                    if not line.startswith("@"):
                        outfile.write(line)
    return job.fileStore.writeGlobalFile(consolidated_mappings)

def get_asms_from_seqfile(seqFile, workflow):
    seqFile = SeqFile(seqFile)
    seqDict = col.OrderedDict(seqFile.pathMap)
    print(seqDict)
    for name, seqURL in seqDict.items():
        seqDict[name] = workflow.importFile(makeURL(seqURL))
    return seqDict

def empty(job):
    """
    An empty job, for easier toil job organization.
    """
    return

## dipcall filter functions

def apply_dipcall_vcf_filter(job, infile, min_var_len=50000, min_mapq=5):
    """Filters out all mappings below min_var_len and min_mapq.
    NOTE: Assumes all secondary mappings are already removed. 
    Also: lastz cigars need to have <score> field filled with mapq, not raw score.
    Args:
        infile (lastz cigar format): [description]
        outfile ([type]): [description]
        min_var_len ([type]): [description]
        min_mapq ([type]): [description]
    """
    # debug = 0
    with open(job.fileStore.readGlobalFile(infile)) as inf:
        filtered = job.fileStore.getLocalTempFile()
        with open(filtered, "w+") as outf:
            for line in inf:
                parsed = line.split()
                # print(parsed, "\t", variation_length(parsed[10:]), "\t", parsed[9])
                # debug += 1
                # if debug == 2:
                #     break
                # if (parsed[3] - parsed[2]) >= min_var_len: This measures the length of the SV from the query point of view. Dipcall also includes deletions in measuring variation length.
                if variation_length(parsed[10:]) >= min_var_len:
                    if int(parsed[9]) >= min_mapq:
                        outf.write(line)

    return job.fileStore.writeGlobalFile(filtered)

def filter_out_secondaries_from_paf(job, paf):
    # secondary_paf = job.fileStore.getLocalTempFile()
    primary_paf = job.fileStore.getLocalTempFile()
    # with open(secondary_paf, "w") as secondary_outf:
    with open(primary_paf, "w") as outf:
        with open(job.fileStore.readGlobalFile(paf)) as inf:
            for line in inf:
                parsed = line.split()
                for i in parsed[11:]:
                    if i[:6] == "tp:A:P" or i[:6] == "tp:A:I":
                        outf.write(line)
                        break
                    # elif i[:5] == "tp:A:S":
                    #     secondary_outf.write(line)
        
    return job.fileStore.writeGlobalFile(primary_paf)
    # return (job.fileStore.writeGlobalFile(primary_paf), job.fileStore.writeGlobalFile(secondary_paf))

def run_prepend_unique_ids(job, assembly_files):
    print("assembly_files", assembly_files)
    sequences = [job.fileStore.readGlobalFile(id) for id in assembly_files.values()]
    print("sequences", sequences)
    renamedInputSeqDir = job.fileStore.getLocalTempDir()
    id_map = {}
    uniqueFas = prependUniqueIDs(sequences, renamedInputSeqDir, id_map)
    print("uniqueFas", uniqueFas)
    uniqueFaIDs = [job.fileStore.writeGlobalFile(seq, cleanup=True) for seq in uniqueFas]
    print("uniqueFaIDs", uniqueFaIDs)
    i = 0
    for assembly in assembly_files:
        assembly_files[assembly] = uniqueFaIDs[i]
        i += 1
    print("assembly_files", assembly_files)
    return assembly_files


## mapping fxns:

def run_cactus_reference_align(job, assembly_files, reference, preprocessing_options, debug_export=False, dipcall_bed_filter=False, dipcall_vcf_filter=False):
    ## Note: this is adapted from run_prepend_unique_ids in cactus_align, in order to maintain order-dependent renamings.
    ## Because cactus-reference-align assumes that all input sequences are ingroups, it does not attempt to avoid renaming outgroup genomes.  
    preprocess_job = job.addChildJobFn(run_prepend_unique_ids, assembly_files)
    assembly_files = preprocess_job.rv()
    mappings = preprocess_job.addFollowOnJobFn(map_all_to_ref, assembly_files, reference, preprocessing_options, debug_export, dipcall_bed_filter, dipcall_vcf_filter).rv()
    return mappings

def map_all_to_ref(job, assembly_files, reference, preprocessing_options, debug_export=False, dipcall_bed_filter=False, dipcall_vcf_filter=False):
    """
    Primarily for use with option_all_to_ref_only. Otherwise, use map_all_to_ref_and_get_poor_mappings.
    assembly_files is an orderedDict (or theoretically works with normal dict, if we can assume order within the dictionary. This is guaranteed at or past python 3.7.)
    """
    lead_job = job.addChildJobFn(empty)

    # map all assemblies to the reference. Don't map reference to reference, though.
    ref_mappings = dict()
    secondary_mappings = dict()
    primary_mappings = dict()
    for assembly, assembly_file in assembly_files.items():
        if assembly != reference:
            # map to a to b
            map_job = lead_job.addChildJobFn(map_a_to_b, assembly_file, assembly_files[reference], (dipcall_bed_filter or dipcall_vcf_filter))
            ref_mappings[assembly] = map_job.rv()

            # if dipcall_bed_filter:
            #     secondaries_filter_job = map_job.addFollowOnJobFn(filter_out_secondaries_from_paf, ref_mappings[assembly])
            #     primary_paf = secondaries_filter_job.rv()

            #     dipcall_bed_filter_job = secondaries_filter_job.addFollowOnJobFn(apply_dipcall_bed_filter.apply_dipcall_bed_filter, primary_paf)
            #     primary_mappings[assembly] = dipcall_bed_filter_job.rv()
            if dipcall_bed_filter:
                secondaries_filter_job = map_job.addFollowOnJobFn(filter_out_secondaries_from_paf, ref_mappings[assembly])
                primary_paf = secondaries_filter_job.rv()

                dipcall_bed_filter_job = secondaries_filter_job.addFollowOnJobFn(apply_dipcall_bed_filter.apply_dipcall_bed_filter, primary_paf)
                bed_filtered_primary_mappings = dipcall_bed_filter_job.rv()

                conversion_job = dipcall_bed_filter_job.addFollowOnJobFn(paf_to_lastz.paf_to_lastz, bed_filtered_primary_mappings)
                lastz_mappings = conversion_job.rv()
            else:
                # convert mapping to lastz (and filter into primary and secondary mappings)
                conversion_job = map_job.addFollowOnJobFn(paf_to_lastz.paf_to_lastz, ref_mappings[assembly])
                lastz_mappings = conversion_job.rv()

            # extract the primary and secondary mappings.
            primary_mappings[assembly] = conversion_job.addFollowOnJobFn(unpack_promise, lastz_mappings, 0).rv()
            secondary_mappings[assembly] = conversion_job.addFollowOnJobFn(unpack_promise, lastz_mappings, 1).rv()

    # consolidate the primary mappings into a single file; same for secondary mappings.
    all_primary = lead_job.addFollowOnJobFn(consolidate_mappings, primary_mappings).rv()
    all_secondary = lead_job.addFollowOnJobFn(consolidate_mappings, secondary_mappings).rv()
    if debug_export:
        return (all_primary, all_secondary, ref_mappings, primary_mappings, secondary_mappings)
    else:
        return (all_primary, all_secondary)

def map_a_to_b(job, a, b, dipcall_filter):
    """Maps fasta a to fasta b.

    Args:
        a (global file): fasta file a. In map_all_to_ref, a is an assembly fasta.
        b (global file): fasta file b. In map_all_to_ref, b is the reference.

    Returns:
        [type]: [description]
    """
    
    # map_to_ref_paf = job.fileStore.writeGlobalFile(job.fileStore.getLocalTempFile())
    tmp = job.fileStore.getLocalTempFile()
    map_to_ref_paf = job.fileStore.writeGlobalFile(tmp)

    if dipcall_filter:
        # note: in dipcall, they include argument "--paf-no-hit". 
        # I don't see why they would include these "mappings", only to be filtered out 
        # later. I have not included the argument.
        subprocess.call(["minimap2", "-c", "-xasm5", "--cs", "-r2k", "-o", job.fileStore.readGlobalFile(map_to_ref_paf),
                        job.fileStore.readGlobalFile(b), job.fileStore.readGlobalFile(a)])
    else:
        subprocess.call(["minimap2", "-cx", "asm5", "-o", job.fileStore.readGlobalFile(map_to_ref_paf),
                        job.fileStore.readGlobalFile(b), job.fileStore.readGlobalFile(a)])
    

    return map_to_ref_paf


## main fxn and interface:

def get_options():
    parser = ArgumentParser()
    Job.Runner.addToilOptions(parser)
    
    # ### For quick debugging of apply_dipcall_bed_filter:
    # parser.add_argument('paf', type=str,
    #                     help='For quick debugging of apply_dipcall_bed_filter.')

    
    # options for basic input/output
    parser.add_argument('seqFile', type=str,
                        help='A file containing all the information specified by cactus in construction. This aligner ignores the newick tree.')
    parser.add_argument('refID', type=str, 
                        help='Specifies which asm in seqFile should be treated as the reference.')
    parser.add_argument("outputFile", type=str, help = "Output pairwise alignment file")

    # dipcall-like filters
    parser.add_argument('--dipcall_bed_filter', action='store_true', 
                        help="Applies filters & minimap2 arguments used to make the bedfile in dipcall. Only affects the primary mappings file. Secondary mappings aren't used in dipcall.")
    parser.add_argument('--dipcall_vcf_filter', action='store_true', 
                        help="Applies filters & minimap2 arguments used to make the vcf in dipcall. Only affects the primary mappings file. Secondary mappings aren't used in dipcall.")
                        
    ## options for importing assemblies:
    # following arguments are only useful under --non_blast_output
    # parser.add_argument('--non_blast_output', action='store_true', 
    #                 help="Instead of using cactus-blast-style prepended ids, use an alternative import method that only alters contig ids if absolutely necessary.")
    # parser.add_argument('--all_unique_ids', action='store_true', 
    #                     help="Only take effect when called with --non_blast_output. Prevents the program from touching the assembly files; the user promises that they don't contain any duplicate contig ids. In reality, there should never be contig renamings if there are no duplicate fasta ids.")
    # parser.add_argument('--overwrite_assemblies', action='store_true', 
    #                     help="When cleaning the assembly files to make sure there are no duplicate contig ids, overwrite the assembly files. Copy them to a neigboring folder with the affix '_edited_for_duplicate_contig_ids' instead.")

    # # Useful in normal asms import
    # parser.add_argument('--assembly_save_dir', type=str, default='./unique_id_assemblies/',
    #                     help='While deduplicating contig ids in the input fastas, save the assemblies in this directory. Ignored when used in conjunction with --overwrite_assemblies.')
                        
    # for debugging:
    parser.add_argument('--debug_export', action='store_true',
                        help='Export several other files for debugging inspection.')
    parser.add_argument('--debug_export_dir', type=str, default='./debug_export_dir/',
                        help='Location of the exported debug files.')

    options = parser.parse_args()
    return options

def main():
    options = get_options()

    with Toil(options) as workflow:
        ## Preprocessing:
        # Import asms; by default, prepends unique IDs in the technique used in cactus-blast.
        asms = get_asms_from_seqfile(options.seqFile, workflow)
        
        # if options.non_blast_output:
        #     asms = import_asms_non_blast_output(options, workflow)
        # else:
        #     asms = import_asms(options, workflow)
            
        ## Perform alignments:
        if not workflow.options.restart:
            alignments = workflow.start(Job.wrapJobFn(run_cactus_reference_align, asms, options.refID, options, options.debug_export, options.dipcall_bed_filter, options.dipcall_vcf_filter))

        else:
            alignments = workflow.restart()

        if options.debug_export:
            # first, ensure the debug dir exists.
            if not os.path.isdir(options.debug_export_dir):
                os.mkdir(options.debug_export_dir)
            
            print(alignments)
            # Then return value is: (all_primary, all_secondary, ref_mappings, primary_mappings, secondary_mappings)
            for asm, mapping_file in alignments[2].items():
                workflow.exportFile(mapping_file, 'file://' + os.path.abspath("mappings_for_" + asm + ".paf"))
            for asm, mapping_file in alignments[3].items():
                workflow.exportFile(mapping_file, 'file://' + os.path.abspath("mappings_for_" + asm + ".cigar"))
            for asm, mapping_file in alignments[4].items():
                workflow.exportFile(mapping_file, 'file://' + os.path.abspath("mappings_for_" + asm + ".cigar.secondry"))

        ## Save alignments:
        if options.dipcall_vcf_filter: # this is substantially less restrictive than the dipcall_bed_filter. 
            dipcall_filtered = workflow.start(Job.wrapJobFn(apply_dipcall_vcf_filter, alignments[0]))
            workflow.exportFile(dipcall_filtered, makeURL(options.outputFile))
            workflow.exportFile(alignments[1], makeURL(options.outputFile + ".unfiltered.secondary"))
        else:
            workflow.exportFile(alignments[0], makeURL(options.outputFile))
            workflow.exportFile(alignments[1], makeURL(options.outputFile + ".secondary"))

if __name__ == "__main__":
    main()