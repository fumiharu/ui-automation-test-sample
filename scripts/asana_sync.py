import os
import re
import sys
import yaml
import argparse
import pathspec
from github import Github, Auth
import asana
from asana.rest import ApiException

def parse_args():
    parser = argparse.ArgumentParser(description='Sync PR to Asana')
    parser.add_argument('--config', default='asana-config.yml', help='Path to config file')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    return parser.parse_args()

def load_config(config_path):
    # Handle missing file gracefully
    if not os.path.exists(config_path):
        print(f"Warning: Config file '{config_path}' not found. Skipping description updates.")
        return {}

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return config if config else {}
    except Exception as e:
        print(f"Warning: Error loading config file '{config_path}': {e}. Skipping description updates.")
        return {}

def get_asana_urls(pr_body):
    """
    Extract Asana URLs from PR body.
    Searches the entire body for URLs matching Asana's domain.
    """
    if not pr_body:
        return []

    # Regex to find URLs starting with https://app.asana.com/
    # \S+ matches non-whitespace characters.
    raw_matches = re.findall(r'https://app\.asana\.com/\S+', pr_body)

    cleaned_urls = []
    for url in raw_matches:
        # Common trailing characters to strip: ) ] } > . , ; : " '
        clean_url = url.rstrip(')]}>.,;:"\'')
        cleaned_urls.append(clean_url)

    return list(set(cleaned_urls)) # unique

def get_matching_rules(changed_files, config):
    """
    Match changed files against config rules.
    Returns a list of dicts with 'team' and 'text'.
    """
    matched_rules = []

    # Handle case where config might be None or empty dict
    if not config:
        return []

    for rule in config.get('rules', []):
        team = rule.get('team')
        paths = rule.get('paths', [])
        text = rule.get('text')

        spec = pathspec.PathSpec.from_lines('gitwildmatch', paths)

        if any(spec.match_file(f) for f in changed_files):
            matched_rules.append({'team': team, 'text': text})

    return matched_rules

def get_task_id_from_url(url):
    """
    Extracts the task ID from an Asana URL.
    """
    # Exclude query parameters first.
    url_path = url.split('?')[0]

    # Split by slashes
    parts = url_path.split('/')

    # Filter empty parts
    parts = [p for p in parts if p]

    # Iterate backwards.
    # Usually the task ID is the last numeric component.
    for part in reversed(parts):
        if part.isdigit():
            return part

    return None

def append_to_html_notes(current_html, append_text_html):
    """
    Appends HTML content to the existing Asana html_notes.
    Asana html_notes are wrapped in <body>...</body>.
    """
    if not current_html:
        return f"<body>{append_text_html}</body>"

    # Insert before closing </body> tag if exists
    if "</body>" in current_html:
        return current_html.replace("</body>", f"{append_text_html}</body>")
    else:
        # Fallback if no body tag found (unlikely for Asana HTML)
        return current_html + append_text_html

def main():
    args = parse_args()

    # Environment variables
    github_token = os.environ.get('GITHUB_TOKEN')
    asana_token = os.environ.get('ASANA_ACCESS_TOKEN')
    repo_name = os.environ.get('GITHUB_REPOSITORY')
    pr_number = os.environ.get('PR_NUMBER')

    if not args.dry_run and (not github_token or not asana_token or not repo_name or not pr_number):
        print("Missing environment variables (GITHUB_TOKEN, ASANA_ACCESS_TOKEN, GITHUB_REPOSITORY, PR_NUMBER)")
        sys.exit(1)

    # Load Config (Graceful)
    config = load_config(args.config)

    # --- GitHub Operations ---
    if args.dry_run:
        print("[DRY-RUN] Fetching PR info...")
        # Mock data for dry run
        pr_title = "Test PR Title"
        pr_html_url = "https://github.com/owner/repo/pull/1"
        pr_body = """
        This is a test PR.
        Here is the task: https://app.asana.com/0/123/456789/f
        Also see [Related Task](https://app.asana.com/0/111/222).
        Duplicate link: https://app.asana.com/0/123/456789
        """
        pr_user_login = "test-user"
        pr_base_ref = "main"
        pr_head_ref = "feature/test"
        changed_files = ["frontend/app.js", "backend/api.py"]
        print(f"[DRY-RUN] PR Body: {pr_body}")
        print(f"[DRY-RUN] Changed Files: {changed_files}")
    else:
        auth = Auth.Token(github_token)
        g = Github(auth=auth)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(int(pr_number))

        pr_title = pr.title
        pr_html_url = pr.html_url
        pr_body = pr.body
        pr_user_login = pr.user.login
        pr_base_ref = pr.base.ref
        pr_head_ref = pr.head.ref

        changed_files = [f.filename for f in pr.get_files()]

    # Extract Asana URLs
    asana_urls = get_asana_urls(pr_body)
    if not asana_urls:
        print("No Asana URLs found in PR description.")
        sys.exit(0)

    print(f"Found Asana URLs: {asana_urls}")

    # Deduplicate Task IDs
    task_ids = set()
    for url in asana_urls:
        tid = get_task_id_from_url(url)
        if tid:
            task_ids.add(tid)
        else:
            print(f"Could not extract task ID from URL: {url}")

    if not task_ids:
        print("No valid Task IDs found.")
        sys.exit(0)

    # Determine rules to apply
    matched_rules = get_matching_rules(changed_files, config)

    # Construct Comment
    # Handle None body
    safe_body = pr_body if pr_body else ""
    comment_text = (
        f"Pull Request merged: {pr_title}\n"
        f"URL: {pr_html_url}\n"
        f"Author: {pr_user_login}\n"
        f"Branch: {pr_head_ref} -> {pr_base_ref}\n"
        f"\n"
        f"{safe_body}"
    )

    # --- Asana Operations ---
    if args.dry_run:
        client = None
    else:
        configuration = asana.Configuration()
        configuration.access_token = asana_token
        client = asana.ApiClient(configuration)

    tasks_api = asana.TasksApi(client)
    stories_api = asana.StoriesApi(client)

    for task_id in task_ids:
        print(f"Processing Task ID: {task_id}")

        # 1. Post Comment
        if args.dry_run:
            print(f"[DRY-RUN] Would post comment to task {task_id}:")
            print(f"---\n{comment_text}\n---")
        else:
            try:
                body = {"data": {"text": comment_text}}
                # Pass opts={} as required by the library signature,
                # but if there are other options they should go to kwargs.
                stories_api.create_story_for_task(body=body, task_gid=task_id, opts={})
                print(f"Comment posted to task {task_id}")
            except ApiException as e:
                print(f"Exception when calling StoriesApi->create_story_for_task: {e}")

        # 2. Update Description (HTML)
        if matched_rules:
            updates = []
            for rule in matched_rules:
                updates.append(f"<strong>担当チーム: {rule['team']}</strong><br>{rule['text']}")

            append_html = "<br><br>" + "<br><br>".join(updates)

            if args.dry_run:
                print(f"[DRY-RUN] Would append HTML to description of task {task_id}:")
                print(f"---\n{append_html}\n---")
            else:
                try:
                    # Fetch current task to get html_notes
                    # Pass opt_fields as keyword argument, separate from opts={}
                    task_response = tasks_api.get_task(task_gid=task_id, opts={}, opt_fields="html_notes")

                    if hasattr(task_response, 'data'):
                        current_html = task_response.data.html_notes
                    else:
                        current_html = getattr(task_response, 'html_notes', '')

                    if current_html is None:
                        current_html = ''

                    # Simple idempotency check
                    if append_html in current_html:
                         print(f"Description already updated for task {task_id}, skipping update.")
                    else:
                        new_html = append_to_html_notes(current_html, append_html)

                        body = {"data": {"html_notes": new_html}}
                        # Pass opts={} as required
                        tasks_api.update_task(body=body, task_gid=task_id, opts={})
                        print(f"Description updated for task {task_id}")
                except ApiException as e:
                    print(f"Exception when calling TasksApi->update_task: {e}")

if __name__ == '__main__':
    main()
