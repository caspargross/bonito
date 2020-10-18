"""
Bonito model evaluator
"""

import time
import torch
import numpy as np
from itertools import starmap
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

from bonito.training import ChunkDataSet
from bonito.util import accuracy, poa, decode_ref, half_supported
from bonito.util import init, load_data, load_model, concat, permute

from torch.utils.data import DataLoader


def main(args):

    poas = []
    init(args.seed, args.device)

    print("* loading data")
    testdata = ChunkDataSet(
        *load_data(limit=args.chunks, shuffle=args.shuffle, directory=args.directory, validation=True)
    )
    dataloader = DataLoader(testdata, batch_size=args.batchsize)
    accuracy_with_coverage_filter = lambda ref, seq: accuracy(ref, seq, min_coverage=args.min_coverage)

    for w in [int(i) for i in args.weights.split(',')]:

        print("* loading model", w)
        model = load_model(args.model_directory, args.device, weights=w)

        print("* calling")
        predictions = []
        t0 = time.perf_counter()

        with torch.no_grad():
            for data, *_ in dataloader:
                if half_supported():
                    data = data.type(torch.float16).to(args.device)
                else:
                    data = data.to(args.device)

                log_probs = permute(model(data), 'TNC', 'NTC')
                predictions.append(log_probs.exp().cpu().numpy().astype(np.float32))

        duration = time.perf_counter() - t0

        references = [decode_ref(target, model.alphabet) for target in dataloader.dataset.targets]
        sequences = [model.decode(probs, beamsize=args.beamsize) for probs in concat(predictions)]
        accuracies = list(starmap(accuracy_with_coverage_filter, zip(references, sequences)))

        if args.poa: poas.append(sequences)

        print("* mean      %.2f%%" % np.mean(accuracies))
        print("* median    %.2f%%" % np.median(accuracies))
        print("* time      %.2f" % duration)
        print("* samples/s %.2E" % (args.chunks * data.shape[2] / duration))

    if args.poa:

        print("* doing poa")
        t0 = time.perf_counter()
        # group each sequence prediction per model together
        poas = [list(seq) for seq in zip(*poas)]
        consensuses = poa(poas)
        duration = time.perf_counter() - t0
        accuracies = list(starmap(accuracy_with_coverage_filter, zip(references, consensuses)))

        print("* mean      %.2f%%" % np.mean(accuracies))
        print("* median    %.2f%%" % np.median(accuracies))
        print("* time      %.2f" % duration)


def argparser():
    parser = ArgumentParser(
        formatter_class=ArgumentDefaultsHelpFormatter,
        add_help=False
    )
    parser.add_argument("model_directory")
    parser.add_argument("--directory", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", default=9, type=int)
    parser.add_argument("--weights", default="0", type=str)
    parser.add_argument("--chunks", default=500, type=int)
    parser.add_argument("--batchsize", default=100, type=int)
    parser.add_argument("--beamsize", default=5, type=int)
    parser.add_argument("--poa", action="store_true", default=False)
    parser.add_argument("--shuffle", action="store_true", default=True)
    parser.add_argument("--min-coverage", default=0.5, type=float)
    return parser
