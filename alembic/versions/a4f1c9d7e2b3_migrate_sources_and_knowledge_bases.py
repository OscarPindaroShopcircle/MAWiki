"""migrate sources and knowledge bases terminology

Revision ID: a4f1c9d7e2b3
Revises: 80d8ee3be5d7
"""

from alembic import op
import sqlalchemy as sa

revision = "a4f1c9d7e2b3"
down_revision = "80d8ee3be5d7"
branch_labels = None
depends_on = None


def _rename_constraint(table: str, old: str, new: str) -> None:
    op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")


def upgrade() -> None:
    op.rename_table("knowledge_bases", "sources")
    op.rename_table("knowledge_base_files", "source_files")
    op.rename_table("knowledge_base_shared_users", "source_shared_users")
    op.alter_column("source_files", "knowledge_base_id", new_column_name="source_id")
    op.alter_column(
        "source_shared_users", "knowledge_base_id", new_column_name="source_id"
    )
    _rename_constraint("sources", "pk_knowledge_bases", "pk_sources")
    _rename_constraint(
        "sources",
        "fk_knowledge_bases_created_by_id_users",
        "fk_sources_created_by_id_users",
    )
    _rename_constraint("source_files", "pk_knowledge_base_files", "pk_source_files")
    _rename_constraint(
        "source_files",
        "fk_knowledge_base_files_file_id_files",
        "fk_source_files_file_id_files",
    )
    _rename_constraint(
        "source_files",
        "fk_knowledge_base_files_knowledge_base_id_knowledge_bases",
        "fk_source_files_source_id_sources",
    )
    _rename_constraint(
        "source_shared_users",
        "pk_knowledge_base_shared_users",
        "pk_source_shared_users",
    )
    _rename_constraint(
        "source_shared_users",
        "fk_knowledge_base_shared_users_knowledge_base_id_knowle_d920",
        "fk_source_shared_users_source_id_sources",
    )
    _rename_constraint(
        "source_shared_users",
        "fk_knowledge_base_shared_users_user_id_users",
        "fk_source_shared_users_user_id_users",
    )

    op.rename_table("rags", "knowledge_bases")
    op.alter_column(
        "knowledge_bases", "source_knowledge_base_id", new_column_name="source_id"
    )
    op.alter_column(
        "knowledge_bases",
        "converted_knowledge_base_id",
        new_column_name="converted_source_id",
    )
    _rename_constraint("knowledge_bases", "pk_rags", "pk_knowledge_bases")
    _rename_constraint(
        "knowledge_bases", "fk_rags_owner_id_users", "fk_knowledge_bases_owner_id_users"
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_rags_source_knowledge_base_id_knowledge_bases",
        "fk_knowledge_bases_source_id_sources",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_rags_converted_knowledge_base_id_knowledge_bases",
        "fk_knowledge_bases_converted_source_id_sources",
    )
    _rename_constraint(
        "knowledge_bases",
        "uq_rags_converted_knowledge_base_id",
        "uq_knowledge_bases_converted_source_id",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_rags_conversion_task_id_tasks",
        "fk_knowledge_bases_conversion_task_id_tasks",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_rags_indexing_task_id_tasks",
        "fk_knowledge_bases_indexing_task_id_tasks",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_rags_index_file_id_files",
        "fk_knowledge_bases_index_file_id_files",
    )
    _rename_constraint(
        "knowledge_bases", "uq_rags_index_file_id", "uq_knowledge_bases_index_file_id"
    )

    op.alter_column("mcp_tool_calls", "rag_id", new_column_name="knowledge_base_id")
    _rename_constraint(
        "mcp_tool_calls",
        "fk_mcp_tool_calls_rag_id_rags",
        "fk_mcp_tool_calls_knowledge_base_id_knowledge_bases",
    )
    op.execute(
        "ALTER TYPE mcp_tool_name RENAME VALUE 'LIST_RAGS' TO 'LIST_KNOWLEDGE_BASES'"
    )

    origin = sa.Enum("USER", "SYSTEM", name="source_origin")
    origin.create(op.get_bind(), checkfirst=False)
    op.add_column("sources", sa.Column("origin", origin, nullable=True))
    op.execute("UPDATE sources SET origin = 'USER'")
    op.execute(
        "UPDATE sources SET origin = 'SYSTEM' FROM knowledge_bases WHERE sources.id = knowledge_bases.converted_source_id"
    )
    op.alter_column("sources", "origin", nullable=False)


def downgrade() -> None:
    op.drop_column("sources", "origin")
    sa.Enum(name="source_origin").drop(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TYPE mcp_tool_name RENAME VALUE 'LIST_KNOWLEDGE_BASES' TO 'LIST_RAGS'"
    )
    _rename_constraint(
        "mcp_tool_calls",
        "fk_mcp_tool_calls_knowledge_base_id_knowledge_bases",
        "fk_mcp_tool_calls_rag_id_rags",
    )
    op.alter_column("mcp_tool_calls", "knowledge_base_id", new_column_name="rag_id")

    _rename_constraint(
        "knowledge_bases", "uq_knowledge_bases_index_file_id", "uq_rags_index_file_id"
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_knowledge_bases_index_file_id_files",
        "fk_rags_index_file_id_files",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_knowledge_bases_indexing_task_id_tasks",
        "fk_rags_indexing_task_id_tasks",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_knowledge_bases_conversion_task_id_tasks",
        "fk_rags_conversion_task_id_tasks",
    )
    _rename_constraint(
        "knowledge_bases",
        "uq_knowledge_bases_converted_source_id",
        "uq_rags_converted_knowledge_base_id",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_knowledge_bases_converted_source_id_sources",
        "fk_rags_converted_knowledge_base_id_knowledge_bases",
    )
    _rename_constraint(
        "knowledge_bases",
        "fk_knowledge_bases_source_id_sources",
        "fk_rags_source_knowledge_base_id_knowledge_bases",
    )
    _rename_constraint(
        "knowledge_bases", "fk_knowledge_bases_owner_id_users", "fk_rags_owner_id_users"
    )
    _rename_constraint("knowledge_bases", "pk_knowledge_bases", "pk_rags")
    op.alter_column(
        "knowledge_bases",
        "converted_source_id",
        new_column_name="converted_knowledge_base_id",
    )
    op.alter_column(
        "knowledge_bases", "source_id", new_column_name="source_knowledge_base_id"
    )
    op.rename_table("knowledge_bases", "rags")

    _rename_constraint(
        "source_shared_users",
        "fk_source_shared_users_user_id_users",
        "fk_knowledge_base_shared_users_user_id_users",
    )
    _rename_constraint(
        "source_shared_users",
        "fk_source_shared_users_source_id_sources",
        "fk_knowledge_base_shared_users_knowledge_base_id_knowle_d920",
    )
    _rename_constraint(
        "source_shared_users",
        "pk_source_shared_users",
        "pk_knowledge_base_shared_users",
    )
    _rename_constraint(
        "source_files",
        "fk_source_files_source_id_sources",
        "fk_knowledge_base_files_knowledge_base_id_knowledge_bases",
    )
    _rename_constraint(
        "source_files",
        "fk_source_files_file_id_files",
        "fk_knowledge_base_files_file_id_files",
    )
    _rename_constraint("source_files", "pk_source_files", "pk_knowledge_base_files")
    _rename_constraint(
        "sources",
        "fk_sources_created_by_id_users",
        "fk_knowledge_bases_created_by_id_users",
    )
    _rename_constraint("sources", "pk_sources", "pk_knowledge_bases")
    op.alter_column(
        "source_shared_users", "source_id", new_column_name="knowledge_base_id"
    )
    op.alter_column("source_files", "source_id", new_column_name="knowledge_base_id")
    op.rename_table("source_shared_users", "knowledge_base_shared_users")
    op.rename_table("source_files", "knowledge_base_files")
    op.rename_table("sources", "knowledge_bases")
