# Linux fleet inventory

Scripts that record what a group of Linux GPU servers contains (hardware, GPUs, disks, power, health) and who is using the GPUs. Only the scripts in `server/` run on the servers. They only run read commands, listed one per line under section headers, and print the raw output, so they can be checked by reading them top to bottom. The parsing happens afterwards, on your machine, in `summary.py`.

| Script | Runs on | As | What it does |
| --- | --- | --- | --- |
| `server/inventory-user.sh` | each server | any user | model, CPU, memory, GPUs and their power caps, who holds each GPU, disks, network, restarts, failed services |
| `server/inventory-root.sh` | each server | root | serial number, memory slots, power supplies and whole-server power (BMC), disk health, boot and kernel error logs |
| `server/usage.sh` | each server | any user | a snapshot of CPU load, memory, and each GPU's use and holder |
| `collect.sh` | your machine | you | runs one of the three above on every server over ssh and saves the output |
| `summary.py` | your machine | you | builds `reports/index.html`, one row per server, from the saved reports |

## Try it on one machine

```
bash server/inventory-user.sh | less
sudo bash server/inventory-root.sh | less
bash server/usage.sh
```

They print to the terminal and write nothing.

## All servers

List the servers in `hosts.txt`, one per line (text after `#` is ignored); `cp hosts.txt.example hosts.txt` gives a starting point. Then:

```
./collect.sh hosts.txt user
./collect.sh hosts.txt root
```

Open `reports/index.html` in a browser. Each row links to the server's full reports.

`collect.sh` logs in with your ssh keys and never asks for a password. The `user` run uses your account as it is. The `root` run uses `sudo -n` to run `server/inventory-root.sh` as root, so your account needs sudo without a password on each server. A server where that fails is reported with the reason (for example "sudo: a password is required"), and the others carry on. A server that fails keeps its earlier report.

## Usage over time

`./collect.sh hosts.txt usage` takes one snapshot of every server (CPU load, memory, and each GPU's use and holder), appends it to `reports/usage-YYYY-MM.log`, and adds the last 7 days to `index.html`: GPUs in use per machine, GPU-hours per user, and an hour-by-hour strip. To record it every 10 minutes, add this line with `crontab -e`:

```
*/10 * * * * cd /path/to/fleet-inventory && ./collect.sh hosts.txt usage > /dev/null
```

Each snapshot takes about a second on each server and moves a few kilobytes.

## Sharing

The `reports` folder is plain text and HTML with no scripts. It is created readable only by you, because the reports contain usernames, addresses and serial numbers. `index.html` alone gives the one-row-per-server overview.

## License

MIT
