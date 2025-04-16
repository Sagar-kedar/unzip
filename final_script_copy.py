import subprocess
import datetime
import random
import time
import os

# Configuration
S3_BUCKET = "testunzip123"
REGION = "ap-south-1"
aws_access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
VERSION = "V3.4.4"
NAMESPACE = "development"  # Change if your pods are in a different namespace

# Pod name patterns and their respective target paths
POD_PATTERN_PATHS = {
    "postgres": "/var/lib/postgresql/data",
    "accesspoint3": "/opt/accesspoint/var",
    "krista-ai-server": "/opt/ai/var/lib",
    "elasticsearch": "/usr/share/elasticsearch/data",
    "platform": "/var/opt/krista"
}

SUMMARY = {}

def run_kubectl_command(command):
    """Run a kubectl command and return output."""
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        print(f"🔴 Output: {e.stderr}")
        return ""

# def extract_pod_pattern(pod_name):
#     for pattern in POD_PATTERN_PATHS:
#         if pattern in pod_name:
#             return pattern
#     return None

def extract_pod_pattern(pod_name):
    for pattern in POD_PATTERN_PATHS:
        if pattern == "accesspoint3":
            if pod_name.startswith("accesspoint3") and pod_name != "accesspoint3-21":  
                return pattern
        else:
            if pattern in pod_name:  # substring match for others
                return pattern
    return None


def is_tool_installed(pod_name, namespace, tool):
    """Check if tool (aws/unzip/tar) is installed inside the pod."""
    output = run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- which {tool}")
    return bool(output and not "not found" in output.lower())

def install_dependencies(pod_name):
    """Install AWS CLI ,unzip, tar if not present."""
    print(f"🔧 Installing awscli, unzip and tar in pod: {pod_name}")
    install_cmd = (
        "apt-get update && "
        "apt-get install -y awscli unzip tar curl ca-certificates && "
        "apt-get clean"
    )
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- /bin/sh -c '{install_cmd}'")

def is_aws_configured(pod_name, namespace):
    result = run_kubectl_command(
        f"kubectl exec {pod_name} -n {namespace} -- test -f /root/.aws/credentials || echo 'not_configured'"
    )
    return "not_configured" not in result

def configure_aws_cli(pod):
    """Configure AWS CLI inside the pod."""
    print(f"\n🔐 Configuring AWS CLI in {pod}")
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod} -- aws configure set aws_access_key_id {aws_access_key_id}")
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod} -- aws configure set aws_secret_access_key {aws_secret_access_key}")
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod} -- aws configure set default.region {REGION}")

def configure_aws_cli_elasticsearch(pod_name):
    if is_aws_configured(pod_name, NAMESPACE):
        print(f"✔ AWS CLI already configured in {pod_name}, skipping config.")
        return

    print(f"⚙️ Installing AWS CLI manually in Elasticsearch pod: {pod_name}")
    install_dir = "/tmp/aws-cli"
    bin_dir = "/tmp/bin"

    # Check if curl exists
    has_curl = run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- which curl")
    if not has_curl:
        print(f"❌ curl not found in {pod_name}. Can't proceed with AWS CLI install.")
        return
    
    # Download and install using curl
    run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- curl 'https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip' -o '/tmp/awscliv2.zip'")
    run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- unzip -o /tmp/awscliv2.zip -d /tmp/")
    run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- chmod +x /tmp/aws/install")
    run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- /tmp/aws/install --install-dir {install_dir} --bin-dir {bin_dir}")

    # Verify installation of AWS CLI
    verify_aws = run_kubectl_command(f"kubectl exec {pod_name} -n {NAMESPACE} -- {bin_dir}/aws --version")
    if not verify_aws:
        print(f"❌ Failed to verify AWS CLI installation in {pod_name}")
        return

    # Configure CLI
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- {bin_dir}/aws configure set aws_access_key_id {aws_access_key_id}")
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- {bin_dir}/aws configure set aws_secret_access_key {aws_secret_access_key}")
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- {bin_dir}/aws configure set default.region {REGION}")
    print(f"✅ AWS CLI configured in Elasticsearch pod: {pod_name}")

def untar_s3_to_pod(pod_name, pod_path, pod_pattern):
    current_date = datetime.datetime.now().strftime("%d-%m-%Y")
    version_folder = f"{VERSION}_{current_date}"
    s3_file_path = f"s3://{S3_BUCKET}/Golden Image/{pod_pattern}_backup.tar.gz"
    local_path = f"{pod_path}/{pod_pattern}_backup.tar.gz"

    print(f"📦 Processing pod: {pod_name} (Pattern: {pod_pattern})")

    # Ensure target path exists
    run_kubectl_command(f"kubectl exec -n {NAMESPACE} {pod_name} -- mkdir -p {pod_path}")

    aws_bin = "/tmp/bin/aws" if "elasticsearch" in pod_name else "aws"

    # Download zip file from S3
    print(f"\n⬇ Downloading from S3: {s3_file_path}")
    download_command = (
        f"kubectl exec -n {NAMESPACE} {pod_name} -- "
        f"env AWS_ACCESS_KEY_ID={aws_access_key_id} "
        f"AWS_SECRET_ACCESS_KEY={aws_secret_access_key} "
        f"{aws_bin} s3 cp '{s3_file_path}' {local_path}"
    )
    download_result = run_kubectl_command(download_command)
    
    if not download_result:  # Check if the download was successful
        print(f"❌ Download failed for {pod_name}. Exiting.")
        return

    # Untar
    print(f"🧩 Unzipping in: {pod_path}/")
    untar_command = f"kubectl exec -n {NAMESPACE} {pod_name} -- tar -xvzf {local_path} -C {pod_path}"
    print(f"📥 Untar command: {untar_command}")

    untar_result = run_kubectl_command(untar_command)
    print(f"📤 Untar output: {untar_result}")

    if "error" in untar_result.lower() or "failed" in untar_result.lower():  # Check for errors in untar command
        print(f"❌ Untar failed for {pod_name}. Error details: {untar_result}")
        # Optionally, log the error to a file or monitoring system
        return  

    # Cleanup
    cleanup_command = f"kubectl exec -n {NAMESPACE} {pod_name} -- rm -f {local_path}"
    run_kubectl_command(cleanup_command)
    print(f"✅ Done with {pod_name}")
    SUMMARY[pod_name] = "Success"

def main():
    print("🔁 Starting restore-from-S3 process using Kubernetes pods")
    get_pods_cmd = f"kubectl get pods -n {NAMESPACE} --no-headers -o custom-columns=':metadata.name'"
    pod_names = run_kubectl_command(get_pods_cmd).split()

    print(f"🔍 Found pods: {pod_names}")

    for pod in pod_names:
        pod_pattern = extract_pod_pattern(pod)
        print(f"➡ Checking pod: {pod}, matched pattern: {pod_pattern}")

        if pod_pattern:
            pod_path = POD_PATTERN_PATHS[pod_pattern]

            if "elasticsearch" in pod:
                configure_aws_cli_elasticsearch(pod)
                untar_s3_to_pod(pod, pod_path, pod_pattern)
            else:
                if not (is_tool_installed(pod, NAMESPACE, "aws") and is_tool_installed(pod, NAMESPACE, "unzip") and is_tool_installed(pod, NAMESPACE, "tar")):
                    install_dependencies(pod)
                configure_aws_cli(pod)
                untar_s3_to_pod(pod, pod_path, pod_pattern)
                time.sleep(random.randint(1, 3))
        else:
            print(f"⚠️ Skipping {pod} (no matching pattern)")

    print("\n📊 Process Summary:")
    for pod, status in SUMMARY.items():
        print(f"   - {pod}: {status}")        

if __name__ == "__main__":
    main()



### use docker image: devops2k23/krista-intern:test
## kubectl run elasticsearch --image=devops2k23/krista-intern:test -n development -- bash -c "sleep infinity
