# The VM job starter

GitHub's scheduled runs land hours late, so the GCP VM starts the time-critical
jobs instead. `deploy/vm/casaa_dispatch.py` runs once a minute from a systemd
timer and starts whatever is due on New York time. The schedule is the `JOBS`
table in that file. The workflows keep their own cron lines as a backstop.

## Adding or replacing the GitHub token
Only the account owner can create it, and it should never pass through a chat.

1. Create a fine-grained token: https://github.com/settings/personal-access-tokens/new?name=casaa-vm-dispatch&description=Start+CasaaFinance+jobs+on+time+from+the+GCP+VM&target_name=xynkro&expires_in=365&actions=write
   Under Repository access, choose **Only select repositories** and pick `CasaaFinance`. The only permission it needs is **Actions: Read and write**.
2. Put it on the VM, with a hidden prompt. The last step tests it:

   ```bash
   ssh -t wavezero.us-east1-b.wavezero-paper-1006 'read -rsp "Paste the GitHub token: " T; echo; mkdir -p ~/.config/casaa-dispatch; (umask 077; printf "%s" "$T" > ~/.config/casaa-dispatch/token); python3 ~/casaa-dispatch/casaa_dispatch.py --check'
   ```

The token lasts a year. When it lapses, or if the VM dies, the first GitHub
backstop run after 11:30 ET sends a "No ideas list today" DM.

## Checking it
```bash
ssh wavezero.us-east1-b.wavezero-paper-1006 'systemctl list-timers casaa-dispatch.timer --no-pager; journalctl -u casaa-dispatch -n 20 --no-pager | grep " ET "'
```

## Changing the schedule
Edit `JOBS`, then from the repo root run `deploy/vm/install_casaa_dispatch.sh`.
