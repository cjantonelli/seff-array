#!/usr/bin/env python
# coding: utf-8
from decimal import Decimal
import textwrap
import math
import argparse
import subprocess
import sys

# Histogram code (with modifications) from
# https://github.com/Kobold/text_histogram

__version__ = 0.1
debug = False


class MVSD(object):
    # A class that calculates a running Mean / Variance
    # / Standard Deviation
    def __init__(self):
        self.is_started = False
        self.ss = Decimal(0)  # (running) sum of square deviations from mean
        self.m = Decimal(0)  # (running) mean
        self.total_w = Decimal(0)  # weight of items seen

    def add(self, x, w=1):
        """ add another datapoint to the MVSD """
        if not isinstance(x, Decimal):
            x = Decimal(x)
        if not self.is_started:
            self.m = x
            self.ss = Decimal(0)
            self.total_w = w
            self.is_started = True
        else:
            temp_w = self.total_w + w
            self.ss += (self.total_w * w * (x - self.m) * (x - self.m)) / temp_w
            self.m += (x - self.m) / temp_w
            self.total_w = temp_w

    def var(self):
        """ returns variance """
        return self.ss / self.total_w

    def sd(self):
        """ returns standard deviation """
        return math.sqrt(self.var())

    def mean(self):
        """ returns mean """
        return self.m


def median(values):
    """ returns median of all values """
    length = len(values)
    if length % 2:
        median_indices = [length / 2]
    else:
        median_indices = [length / 2 - 1, length / 2]

    values = sorted(values)
    return sum([values[int(i)] for i in median_indices]) / len(median_indices)


def histogram(
    stream,
    req_mem=0,
    req_cpus=0,
    req_time=0,
    form=0,
    minimum=None,
    maximum=None,
    buckets=None,
    custbuckets=None,
    calc_msvd=True,
):
    """
    Loop over the stream and add each entry to the dataset,
    printing out the histogram at the end.
    

    stream: list of data points
    req_mem: requested memory for the job array
    req_cpus: requested cores for the job array
    req_time: requested runtime for the job array
    (removed) timeflag: distinguishes between the memory and time histograms
    (added) form: 0 (memory), 1 (time), 2 (cpu)
    minimum: minimum value for graph
    maximum: maximum value for graph
    buckets: Number of buckets to use for the histogram
    custbuckets: Comma seperated list of bucket edges for the histogram
    calc_msvd: Calculate and display Mean, Variance and SD.
    """
    if not minimum or not maximum:
        # glob the iterator here so we can do min/max on it
        data = list(stream)
    else:
        data = stream

    # Error handling for empty list of jobs
    # if not data:
    #     if timeflag:
    #         print('Job(s) have not yet completed: No time info to show.')
    #     else:
    #         print('Job(s) have not yet completed: No memory info to show.')
    #     return

    bucket_scale = 1

    if minimum:
        min_v = Decimal(minimum)
    else:
        min_v = min(data)
    if maximum:
        max_v = Decimal(maximum)
    else:
        max_v = max(data)

    if not max_v >= min_v:
        raise ValueError("max must be >= min. max:%s min:%s" % (max_v, min_v))

    diff = max_v - min_v
    boundaries = []
    bucket_counts = []

    if custbuckets:
        bound = custbuckets.split(",")
        bound_sort = sorted(map(Decimal, bound))

        # if the last value is smaller than the maximum, replace it
        # if bound_sort[-1] < max_v:
        #     bound_sort[-1] = max_v

        # iterate through the sorted list and append to boundaries
        for x in bound_sort:
            if x <= max_v:
                boundaries.append(x)
            else:
                boundaries.append(max_v)
                break

        """beware: the min_v is not included in the boundaries,
        so no need to do a -1!"""
        bucket_counts = [0 for x in range(len(boundaries))]
        buckets = len(boundaries)
    else:
        buckets = buckets or 10
        if buckets <= 0:
            raise ValueError("# of buckets must be > 0")
        step = diff / buckets
        bucket_counts = [0 for x in range(buckets)]
        for x in range(buckets):
            boundaries.append(min_v + (step * (x + 1)))

        if req_mem:
            req_mem_int = str_to_mb(req_mem, int(req_cpus))

            # OPTIONAL STYLE CHOICE:
            # lastly, redo the boundaries so that the maximum
            # of the last bin is the total requested memory
            # boundaries = [(req_mem_int/10)*x  for x in range(1,11)]

    skipped = 0
    samples = 0
    mvsd = MVSD()
    accepted_data = []

    for value in data:
        samples += 1
        if calc_msvd:
            mvsd.add(value)
            accepted_data.append(value)
        # find the bucket this goes in
        if value < min_v or value > max_v:
            skipped += 1
            continue
        for bucket_postion, boundary in enumerate(boundaries):
            if value <= boundary:
                bucket_counts[bucket_postion] += 1
                break

    # auto-pick the hash scale
    if max(bucket_counts) > 60:
        bucket_scale = int(max(bucket_counts) / 60)

    # histograms for time and memory usage are formatted differently
    if form == 1:
        print("========== Elapsed Time ==========")
        print(
            "# NumSamples = %d; Min = %s; Max = %s"
            % (samples, int_to_time(round(min_v)), int_to_time(round(max_v)))
        )
        if skipped:
            print(
                "# %d value%s outside of min/max" % (skipped, skipped > 1 and "s" or "")
            )
        if calc_msvd:
            print(
                "# Mean = %s; SD = %s; Median %s"
                % (
                    int_to_time(round(mvsd.mean())),
                    int_to_time(round(mvsd.sd())),
                    int_to_time(round(median(accepted_data))),
                )
            )

        print("# each ∎ represents a count of %d" % bucket_scale)
        bucket_min = min_v * 0.9
        bucket_max = min_v * 0.9
        for bucket in range(buckets):
            bucket_min = bucket_max
            bucket_max = boundaries[bucket]
            bucket_count = bucket_counts[bucket]
            star_count = 0
            if bucket_count:
                star_count = bucket_count // bucket_scale
            print(
                "{:10s} - {:10s} [{:4d}]: {}".format(
                    int_to_time(round(bucket_min)),
                    int_to_time(round(bucket_max)),
                    bucket_count,
                    "∎" * star_count,
                )
            )

        if req_time != 0 and mvsd.mean() * 4 <= time_to_int(req_time):
            print("*" * 80)
            print(
                "The requested runtime was %s.\
                 \nThe average runtime was %s.\
                 \nRequesting less time would allow jobs to run more quickly."
                % (req_time, int_to_time(round(mvsd.mean())))
            )
            print("*" * 80)
        else:
            print("The requested runtime was %s." % req_time)

    elif form == 0:
        print("========== Max Memory Usage ==========")
        print(
            "# NumSamples = %d; Min = %0.2f MB; Max = %0.2f MB"
            % (samples, min_v, max_v)
        )
        if skipped:
            print(
                "# %d value%s outside of min/max" % (skipped, skipped > 1 and "s" or "")
            )
        if calc_msvd:
            print(
                "# Mean = %0.2f MB; Variance = %0.2f MB; "
                "SD = %0.2f MB; Median %0.2f MB"
                % (mvsd.mean(), mvsd.var(), mvsd.sd(), median(accepted_data))
            )

        print("# each ∎ represents a count of %d" % bucket_scale)
        bucket_min = min_v * 0.9
        bucket_max = min_v * 0.9
        for bucket in range(buckets):
            bucket_min = bucket_max
            bucket_max = boundaries[bucket]
            bucket_count = bucket_counts[bucket]
            star_count = 0
            if bucket_count:
                star_count = bucket_count // bucket_scale
            print(
                "%10.4f - %10.4f MB [%4d]: %s"
                % (bucket_min, bucket_max, bucket_count, "∎" * star_count)
            )
        if req_mem_int / 5 >= mvsd.mean():
            print("*" * 80)
            print(
                "The requested memory was %s."
                "\nThe average memory usage was %s."
                "\nRequesting less memory would allow"
                " jobs to run more quickly."
                % (mb_to_str(req_mem_int), mb_to_str(round(mvsd.mean())))
            )
            print("*" * 80)
        else:
            print("The requested memory was %s." % mb_to_str(req_mem_int))
    else:
        print("========== CPU Utilization ==========")
        print(
            "# NumSamples = %d; Min = %s%%; Max = %s%%"
            % (samples, int(round(min_v)), int(round(max_v)))
        )
        if skipped:
            print(
                "# %d value%s outside of min/max" % (skipped, skipped > 1 and "s" or "")
            )
        if calc_msvd:
            print(
                "# Mean = %s%%; SD = %s%%; Median %s%%"
                % (
                    int(round(mvsd.mean())),
                    int(round(mvsd.sd())),
                    int(round(median(accepted_data))),
                )
            )

        print("# each ∎ represents a count of %d" % bucket_scale)
        bucket_min = min_v * 0.9
        bucket_max = min_v * 0.9
        for bucket in range(1, buckets):
            bucket_min = boundaries[bucket - 1]
            bucket_max = boundaries[bucket]
            bucket_count = bucket_counts[bucket]
            star_count = 0
            if bucket_count:
                star_count = bucket_count // bucket_scale
            print(
                "%6.2f%% - %6.2f%% [%4d]: %s"
                % (bucket_min, bucket_max, bucket_count, "∎" * star_count)
            )
        if 50 >= mvsd.mean() and req_cpus > 1:
            print("*" * 80)
            print(
                "The requested number of cores is %s."
                "\nThe average CPU usage was %s%%."
                "\nConsider requesting less cores would allow"
                " jobs to run more quickly." % (req_cpus, round(mvsd.mean()))
            )
            print("*" * 80)
        else:
            print("The requested number of CPUs is %s." % req_cpus)


def time_to_int(time):
    """ converts [dd-[hh:]]mm:ss time to seconds """
    days, hours = 0, 0

    if "-" in time:
        days = int(time.split("-")[0]) * 86400
        time = time.split("-")[1]
    time = time.split(":")

    if len(time) > 2:
        hours = int(time[0]) * 3600

    mins = int(time[-2]) * 60
    secs = float(time[-1])

    return days + hours + mins + secs


def int_to_time(secs):
    """ converts seconds to [dd-[hh:]]mm:ss """
    days = secs // 86400
    secs %= 86400
    hours = secs // 3600
    secs %= 3600
    mins = secs // 60
    secs %= 60

    if days > 0:
        return (
            "{:02.0f}".format(days)
            + "-"
            + "{:02.0f}".format(hours)
            + ":"
            + "{:02.0f}".format(mins)
            + ":"
            + "{:05.2f}".format(secs)
        )
    elif hours > 0:
        return (
            "{:02.0f}".format(hours)
            + ":"
            + "{:02.0f}".format(mins)
            + ":"
            + "{:05.2f}".format(secs)
        )

    return "{:02.0f}".format(mins) + ":" + "{:05.2f}".format(secs)


# convert megabytes to mem_str with units
def mb_to_str(num):
    if num > 10 ** 3:
        return str(round(num / 1000.0, 2)) + "GB"
    elif num < 1:
        return str(round(num * 1000.0, 2)) + "KB"
    return str(round(num, 2)) + "MB"


# convert mem str to number of megabytes
def str_to_mb(s, cores=1):
    unit = s[-2:]
    num = float(s[:-2])
    if "c" in unit:
        num *= cores

    unit = unit.replace("c", "B").replace("n", "B")
    
    if unit == "GB":
        return round(num * 1000, 2)
    elif unit == "KB":
        return round(num / 1000, 2)
    return round(num, 2)


# convert a mem str to the right unit with
# num part between 1 <= x < 1000
def fix_mem_str(s, c=1):
    return mb_to_str(str_to_mb(s, c))


def print_states(d):
    print("---------------------")
    print("Job States")
    for state, value in d.items():
        print(state + ": " + str(value))
    print("---------------------")


def main(arrayID, m, t, c, v):
    data_collector = {}  # key = job_id; val = [maxRSS, elapsed, cpuTime]
    elapsed_list = []
    maxRSS_list = []
    cpuTime_list = []
    cpuTime_sum, elapsed_sum, rss_sum = 0, 0, 0
    job_states = {}
    skipped = 0

    if debug:
        file = open(sys.argv[1], "r")
        result = file.read()
    else:
        query = (
            "sacct -n -P -j %s --format=JobID,JobName,MaxRSS,Elapsed,"
            "ReqMem,ReqCPUS,Timelimit,State,TotalCPU,User,Group,Cluster,ExitCode"
            % arrayID
        )
        result = subprocess.check_output([query], shell=True)

    if sys.version_info[0] >= 3:
        result = str(result, "utf-8")

    data = result.split("\n")

    data = [x for x in data if x != ""]  # remove all empty lines

    if len(data) == 0:
        print("Job not found.")
        return

    # parse job states from input
    jobs_seen = []
    for line in data:
        state = line.split("|")[7]
        jobID = line.split("|")[0].split(".")[0]

        if jobID in jobs_seen:
            continue

        jobs_seen.append(jobID)

        if state in job_states.keys():
            job_states[state] += 1
        else:
            job_states[state] = 1

    # print list of job states for job arrays
    if len(job_states.keys()) > 1:
        print_states(job_states)

    job_state = data[0].split("|")[7]

    if job_state != "COMPLETED" and job_state != "FAILED":
        print("No info to show for job %s" % arrayID)
        print("Current status for job: %s" % job_state)
        return

    req_mem = data[0].split("|")[4]
    req_cpus = data[0].split("|")[5]
    req_time = data[0].split("|")[6]
    for line in data:
        if line == "" or line == "\n":
            continue
        # print(line)
        line = line.split("|")
        jobID = line[0].split(".")[0]
        maxRSS = line[2]
        elapsed = line[3]
        cpuTime = line[8]
        state = line[7]

        if maxRSS == "" or cpuTime == "":
            continue

        maxRSS = str_to_mb(maxRSS + "B")
        cpuTime = time_to_int(cpuTime)
        elapsedTime = time_to_int(elapsed)
        num_req_cpus = int(req_cpus)

        if elapsedTime == 0 or num_req_cpus == 0:
            skipped += 1
            continue

        used_cpu = 100 * cpuTime / (elapsedTime * num_req_cpus)
        cpuTime_sum += cpuTime

        if used_cpu > 100:
            used_cpu = 100

        if jobID not in data_collector.keys():
            data_collector[jobID] = [float(maxRSS), elapsed, used_cpu]
            elapsed_sum += elapsedTime
            rss_sum += float(maxRSS)
        else:
            data_collector[jobID][0] += float(maxRSS)
            data_collector[jobID][2] += used_cpu

    for triple in data_collector.values():
        maxRSS_list.append(triple[0])
        elapsed_list.append(triple[1])
        cpuTime_list.append(triple[2])

    line = data[0].split("|")
    user = line[9]
    group = line[10]
    cluster = line[11]
    exit_code = line[12] if ":" not in line[12] else line[12].split(":")[0]
    data_len = len(data_collector.keys())

    # normal seff stats
    print("Job ID: %s" % arrayID)
    print("Cluster: %s" % cluster)
    print("User/Group: %s/%s" % (user, group))
    print("State: %s (exit code %s)" % (job_state, exit_code))
    print("Cores: %s" % req_cpus)
    print("Average CPU Utilized: %s" % int_to_time(cpuTime_sum / len(cpuTime_list)))
    print(
        "Average CPU Efficiency: %0.2f%% of %s core-walltime"
        % (100 * cpuTime_sum / elapsed_sum, int_to_time(elapsed_sum))
    )
    print("Job Wall-clock time: %s" % int_to_time(elapsed_sum))
    print("Average Memory Utilized: %s" % mb_to_str(rss_sum / data_len))
    print(
        "Memory Efficiency: %0.2f%% of %s"
        % (
            100 * rss_sum / str_to_mb(req_mem, int(req_cpus)) / data_len,
            fix_mem_str(req_mem, int(req_cpus)),
        )
    )

    # if verbose flag is false, stop
    if not v:
        return

    # If all jobs omitted print warning and stop, else just print warning
    if data_len == 0:
        print("Omitted %i (all) jobs. No job statistics to show." % skipped)
        return
    elif skipped > 0:
        print("*****")
        print(
            "Warning: Omitted %i jobs. The elapsed time for these jobs is zero seconds."
            % skipped
        )
        print("*****")

    # single job handling
    if len(maxRSS_list) == 1:
        if m:
            print("Memory Usage: %sMB" % maxRSS_list[0])
            print("Requested Memory: %s" % fix_mem_str(req_mem))

            req_mem_int = str_to_mb(req_mem)
            mem_eff = (float(maxRSS_list[0]) / req_mem_int * int(req_cpus)) * 100
            print("This job used %0.2f%% of its requested memory." % mem_eff)
            if mem_eff < 20:
                print("Consider requesting less memory to decrease waittime. ")
            print("")

        if t:
            print("Elapsed Time: %s" % elapsed_list[0])
            print("Requested Time: %s" % req_time)

            time_eff = time_to_int(elapsed_list[0]) / time_to_int(req_time) * 100
            print("This job used %0.2f%% of its requested time." % time_eff)
            if time_eff < 20:
                print("Consider requesting less time to decrease waittime. ")
            print("")

        if c:
            print("Cores Requested: %s" % req_cpus)
            print("CPU efficiency for this job is %0.2f%%." % cpuTime_list[0])
            if cpuTime_list[0] < 50 and req_cpus > 1:
                print("Consider requesting less cores to decrease waittime.")
    else:
        if m:
            histogram(maxRSS_list, form=0, req_mem=req_mem, req_cpus=req_cpus)
            print("")
        if t:
            histogram(list(map(time_to_int, elapsed_list)), form=1, req_time=req_time)
            print("")
        if c:
            buckets = "0,10,20,30,40,50,60,70,80,90,100"
            histogram(cpuTime_list, form=2, req_cpus=req_cpus, custbuckets=buckets)


if __name__ == "__main__":

    desc = (
        """
    seff-array v%s
    https://github.com/ycrc/seff-array
    ---------------
    An extension of the Slurm command 'seff' designed to handle job arrays and display information in a histogram.

    seff-array generates two histograms; one for the maximum memory usage of each job in the array, and one for the runtime of each job.

    To use seff-array on the job array with ID '12345678', simply run 'seff-array 12345678'.
    You can also use seff-array on a text file containing the results of the command:
        'sacct -p -j <your_id> --format=JobID,JobName,MaxRSS,Elapsed,ReqMem,ReqCPUS,Timelimit'
    To do this, use the '-i' flag: 'seff-array -i <filename.txt>'

    Other things can go here in the future.
    -----------------
    """
        % __version__
    )

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(desc),
    )
    parser.add_argument("jobid")
    parser.add_argument("-m", "--mem", action="store_true", dest="m")
    parser.add_argument("-t", "--time", action="store_true", dest="t")
    parser.add_argument("-c", "--cpu", action="store_true", dest="c")
    parser.add_argument("-v", "--verbose", action="store_true", dest="v")
    args = parser.parse_args()
    # print(args.m, args.t, args.c)
    if not (args.m or args.t or args.c):
        args.m, args.t, args.c = True, True, True
    main(args.jobid, args.m, args.t, args.c, args.v)
