from pr_repair.config import AppConfig
from pr_repair.ingestion.pr_collector import collect_candidate_prs
from pr_repair.types import PRRef


class FakeGitHubConnector:
    def list_open_prs(
        self, repo_owner: str, repo_name: str, include_drafts: bool = False
    ) -> list[PRRef]:
        assert repo_owner == "owner"
        assert repo_name == "repo"
        assert include_drafts is False
        return [
            PRRef(
                repo_owner="owner",
                repo_name="repo",
                pr_number=3,
                title="low",
                head_branch="feature/low",
                base_branch="main",
                head_sha="sha-3",
                is_draft=False,
                author="user-3",
                labels=[],
                changed_files=["a.py"],
            ),
            PRRef(
                repo_owner="owner",
                repo_name="repo",
                pr_number=2,
                title="high",
                head_branch="feature/high",
                base_branch="main",
                head_sha="sha-2",
                is_draft=False,
                author="user-2",
                labels=["security", "requested-changes"],
                changed_files=["a.py", "b.py"],
            ),
            PRRef(
                repo_owner="owner",
                repo_name="repo",
                pr_number=1,
                title="draft",
                head_branch="feature/draft",
                base_branch="main",
                head_sha="sha-1",
                is_draft=True,
                author="user-1",
                labels=["bug"],
                changed_files=[],
            ),
        ]


def test_collect_candidate_prs_is_priority_ordered_and_limited(tmp_path) -> None:
    config = AppConfig(
        github_token="token",
        github_repository="owner/repo",
        max_prs=2,
        verify_command=["make", "agent-check"],
        mode="dry_run",
        output_dir=tmp_path,
    )

    prs = collect_candidate_prs(config, github_connector=FakeGitHubConnector())

    assert [pr.pr_number for pr in prs] == [2, 3]
