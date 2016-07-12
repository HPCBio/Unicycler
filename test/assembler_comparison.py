#!/usr/bin/env python3
"""
Tool for comparing the assemblies made by Unicycler, SPAdes, hybridSPAdes and npScarf.

Usage:
assembler_comparison.py --reference path/to/reference.fasta --relative_depths 1.0,1.5,2.0

Author: Ryan Wick
email: rrwick@gmail.com
"""

import random, os, subprocess, argparse, sys, time


def main():
    args = get_args()
    illumina_1, illumina_2 = make_fake_illumina_reads(args)
    quast_results = create_quast_results_table()
    run_unicycler_no_long(illumina_1, illumina_2, args.reference, quast_results)
    run_regular_spades(illumina_1, illumina_2, args.reference, quast_results)

    # Run Cerulean with short reads only? And then QUAST.

    # Run NaS with short reads only? And then QUAST.

    # Generate simulated long reads at a defined error rate.

    # Run unicycler with all reads to get the alignments and a max depth value.

    # Sample loop:

        # Randomly subsample the reads, save to fastq.gz with a sample number.

        # Calculate the average depth, relative to the main chromosome.

        # Before running Unicycler, create the output folder and copy in the unbridged graph.

        # Go through the full alignment SAM file and make a SAM with just the subsampled reads. Copy that to the output folder.

        # Run Unicycler (should be able to skip the short read assembly and alignment and get right to the bridging)

        # Delete everything but the final graph, final assembly, reads and sam (to save space but allow for easy re-running)

        # Run QUAST on Unicycler assembly

        # Run hybridSPAdes

        # Run QUAST on hybridSPAdes assembly

        # Run npScarf (using SPAdes contigs)

        # Run QUAST on npScarf assembly

        # Run ALLPATHS-LG

        # Run QUAST on ALLPATHS-LG assembly

        # Gather up all QUAST results in a table


def get_args():
    """
    Specifies the command line arguments required by the script.
    """
    parser = argparse.ArgumentParser(description='Assembly tester')
    parser.add_argument('--reference', type=str, required=True,
                        help='The reference genome to shred and reassemble')
    parser.add_argument('--relative_depths', type=str, default='1.0',
                        help='Comma-delimited list of relative read depths for each sequence '
                             'in the reference FASTA')
    parser.add_argument('--illumina_depth', type=float, default=40.0,
                        help='Base read depth for fake Illumina reads')
    parser.add_argument('--rotation_count', type=int, default=100, required=False,
                        help='The number of times to run read simulators with random start '
                             'positions')

    return parser.parse_args()


def make_fake_illumina_reads(args):
    """
    Runs ART to generate fake Illumina reads. Runs ART separate for each sequence in the reference
    file (to control relative depth) and at multiple sequence rotations (to ensure circular
    assembly).
    """
    read_filename_1 = os.path.abspath('fake_illumina_1.fastq')
    read_filename_2 = os.path.abspath('fake_illumina_2.fastq')
    if os.path.isfile(read_filename_1) and os.path.isfile(read_filename_2):
        return read_filename_1, read_filename_2
    print('Generating synthetic Illumina reads')

    references = load_fasta(args.reference)
    relative_depths = [float(x.strip()) for x in args.relative_depths.split(',')]
    if len(references) != len(relative_depths):
        quit_with_error('you must provide exactly one relative depth for each reference sequence')

    # This will hold all simulated reads. Each read is a list of 8 strings: the first four are for
    # the first read in the pair, the second four are for the second.
    read_pairs = []
    for i, ref in enumerate(references):

        depth = relative_depths[i] * args.illumina_depth
        depth_per_rotation = depth / args.rotation_count
        ref_seq = ref[1]

        for _ in range(args.rotation_count):

            # Randomly rotate the sequence.
            random_start = random.randint(0, len(ref_seq) - 1)
            rotated = ref_seq[random_start:] + ref_seq[:random_start]

            # Save the rotated sequence to FASTA.
            temp_fasta_filename = 'temp.fasta'
            temp_fasta = open(temp_fasta_filename, 'w')
            temp_fasta.write('>' + ref[0] + '\n')
            temp_fasta.write(rotated + '\n')
            temp_fasta.close()

            read_pairs += run_art(temp_fasta_filename, depth_per_rotation)
            os.remove(temp_fasta_filename)

    random.shuffle(read_pairs)
    reads_1 = open(read_filename_1, 'w')
    reads_2 = open(read_filename_2, 'w')
    for read_pair in read_pairs:
        reads_1.write(read_pair[0] + '\n')
        reads_1.write(read_pair[1] + '\n')
        reads_1.write(read_pair[2] + '\n')
        reads_1.write(read_pair[3] + '\n')
        reads_2.write(read_pair[4] + '\n')
        reads_2.write(read_pair[5] + '\n')
        reads_2.write(read_pair[6] + '\n')
        reads_2.write(read_pair[7] + '\n')
    reads_1.close()
    reads_2.close()
    return read_filename_1, read_filename_2


def run_art(input_fasta, depth):
    """
    Runs ART with some fixed settings: 125 bp paired-end reads, 400 bp fragments, HiSeq 2500.
    Returns reads as list of list of strings.
    """
    art_command = ['art_illumina', '--seqSys', 'HS25', '--in', input_fasta, '--len', '125',
                   '--mflen', '400', '--sdev', '60', '--fcov', str(depth), '--out', 'art_output']
    try:
        subprocess.check_output(art_command, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        quit_with_error('ART encountered an error:\n' + e.output.decode())

    output_fastq_1_filename = 'art_output1.fq'
    output_fastq_2_filename = 'art_output2.fq'
    try:
        with open(output_fastq_1_filename, 'rt') as f:
            fastq_1_lines = f.read().splitlines()
        with open(output_fastq_2_filename, 'rt') as f:
            fastq_2_lines = f.read().splitlines()
        pair_count = int(len(fastq_1_lines) / 4)
    except FileNotFoundError:
        pair_count = 0
        quit_with_error('Could not find ART output read files')

    os.remove('art_output1.fq')
    os.remove('art_output2.fq')
    os.remove('art_output1.aln')
    os.remove('art_output2.aln')

    read_pairs = []
    i = 0
    for _ in range(pair_count):
        name_1 = fastq_1_lines[i]
        name_2 = fastq_2_lines[i]
        seq_1 = fastq_1_lines[i + 1]
        seq_2 = fastq_2_lines[i + 1]
        spacer_1 = fastq_1_lines[i + 2]
        spacer_2 = fastq_2_lines[i + 2]
        qual_1 = fastq_1_lines[i + 3]
        qual_2 = fastq_2_lines[i + 3]

        read_pairs.append((name_1, seq_1, spacer_1, qual_1, name_2, seq_2, spacer_2, qual_2))
        i += 4

    return read_pairs


def run_regular_spades(illumina_1, illumina_2, reference, all_quast_results):
    """
    Runs SPAdes with only short reads (i.e. not hybridSPAdes).
    """
    spades_dir = 'spades_short_only'
    spades_assembly = os.path.join(spades_dir, 'scaffolds.fasta')
    if not os.path.isfile(spades_assembly):
        spades_start_time = time.time()
        print('Running SPAdes with short reads only')
        if not os.path.exists(spades_dir):
            os.makedirs(spades_dir)
        spades_command = ['spades.py', '-1', illumina_1, '-2', illumina_2, '--careful',
                          '-o', spades_dir]
        try:
            subprocess.check_output(spades_command, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            quit_with_error('SPAdes encountered an error:' + e.output.decode())
        spades_time = time.time() - spades_start_time
        run_quast(spades_assembly, reference, all_quast_results, 'SPAdes', 0.0, spades_time)


def run_unicycler_no_long(illumina_1, illumina_2, reference, all_quast_results):
    unicycler_dir = 'unicycler_short_only'
    unicycler_assembly = os.path.join(unicycler_dir, 'assembly.fasta')
    if not os.path.isfile(unicycler_assembly):
        unicycler_start_time = time.time()
        print('Running Unicycler with short reads only')
        if not os.path.exists(unicycler_dir):
            os.makedirs(unicycler_dir)
        unicycler_command = ['unicycler', '--short1', illumina_1, '--short2', illumina_2,
                             '--no_long', '--out', unicycler_dir, '--keep_temp', '0']
        try:
            subprocess.check_output(unicycler_command, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            quit_with_error('Unicycler encountered an error:' + e.output.decode())
        unicycler_time = time.time() - unicycler_start_time
        run_quast(unicycler_assembly, reference, all_quast_results, 'Unicycler', 0.0,
                  unicycler_time)


def create_quast_results_table():
    quast_results_filename = 'quast_results.tsv'
    if not os.path.isfile(quast_results_filename):
        quast_results = open(quast_results_filename, 'w')
        quast_results.write("Assembler\t"
                            "Long read depth\t"
                            "Run time (seconds)\t"
                            "# contigs (>= 0 bp)\t"
                            "# contigs (>= 1000 bp)\t"
                            "# contigs (>= 5000 bp)\t"
                            "# contigs (>= 10000 bp)\t"
                            "# contigs (>= 25000 bp)\t"
                            "# contigs (>= 50000 bp)\t"
                            "Total length (>= 0 bp)\t"
                            "Total length (>= 1000 bp)\t"
                            "Total length (>= 5000 bp)\t"
                            "Total length (>= 10000 bp)\t"
                            "Total length (>= 25000 bp)\t"
                            "Total length (>= 50000 bp)\t"
                            "# contigs\t"
                            "Largest contig\t"
                            "Total length\t"
                            "Reference length\t"
                            "GC (%)\t"
                            "Reference GC (%)\t"
                            "N50\t"
                            "NG50\t"
                            "N75\t"
                            "NG75\t"
                            "L50\t"
                            "LG50\t"
                            "L75\t"
                            "LG75\t"
                            "# misassemblies\t"
                            "# misassembled contigs\t"
                            "Misassembled contigs length\t"
                            "# local misassemblies\t"
                            "# unaligned contigs\t"
                            "Unaligned length\t"
                            "Genome fraction (%)\t"
                            "Duplication ratio\t"
                            "# N's per 100 kbp\t"
                            "# mismatches per 100 kbp\t"
                            "# indels per 100 kbp\t"
                            "Largest alignment\t"
                            "NA50\t"
                            "NGA50\t"
                            "NA75\t"
                            "NGA75\t"
                            "LA50\t"
                            "LGA50\t"
                            "LA75\t"
                            "LGA75\n")
        quast_results.close()
    return quast_results_filename


def run_quast(assembly, reference, all_quast_results, assembler_name, long_read_depth, run_time):
    run_name = assembler_name + ' ' + str(long_read_depth) + 'x'
    print('Running QUAST for', run_name)
    quast_dir = os.path.join('quast_results', run_name)
    this_quast_results = os.path.join(quast_dir, 'transposed_report.tsv')
    if not os.path.isfile(this_quast_results):
        quast_command = ['quast.py', assembly, '-R', reference, '-o', quast_dir,
                         '-l', '"' + run_name + '"']
        try:
            subprocess.check_output(quast_command, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            quit_with_error('QUAST encountered an error:' + e.output.decode())

    with open(this_quast_results, 'rt') as results:
        results.readline()  # header line
        with open(all_quast_results, 'at') as all_results:
            quast_line = [assembler_name, str(long_read_depth), str(run_time)]
            quast_line += results.readline().split('\t')[1:]
            all_results.write('\t'.join(spades_quast_line))


def load_fasta(filename):
    """
    Returns a list of tuples (header, seq) for each record in the fasta file.
    """
    fasta_seqs = []
    fasta_file = open(filename, 'rt')
    name = ''
    sequence = ''
    for line in fasta_file:
        line = line.strip()
        if not line:
            continue
        if line[0] == '>':  # Header line = start of new contig
            if name:
                fasta_seqs.append((name.split()[0], sequence))
                sequence = ''
            name = line[1:]
        else:
            sequence += line
    if name:
        fasta_seqs.append((name.split()[0], sequence))
    fasta_file.close()
    return fasta_seqs


def quit_with_error(message):
    print('Error:', message, file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
