"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { ErrorPanel } from "@/components/ui/error-panel";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/client";
import { createScene, updateScene, type SceneView } from "../api";
import styles from "./form-dialog.module.css";

export interface EvaluationSetFormDialogProps {
  open: boolean;
  /** Present when editing an existing scene; absent when creating. */
  scene?: SceneView | null;
  onClose: () => void;
  onSaved: (scene: SceneView) => void;
}

export function EvaluationSetFormDialog({
  open,
  scene,
  onClose,
  onSaved,
}: EvaluationSetFormDialogProps): React.JSX.Element {
  const isEdit = Boolean(scene);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Seed only on the closed -> open transition. Keying on the transition (not
  // on the scene object reference) means a concurrent reload that produces a
  // new scene object cannot wipe what the user is currently typing.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (open && !wasOpen.current) {
      setName(scene?.name ?? "");
      setDescription(scene?.description ?? "");
      setNameError(null);
      setFormError(null);
      setSubmitting(false);
    }
    wasOpen.current = open;
  }, [open, scene]);

  async function handleSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (submitting) return;

    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("评测集名称不能为空白。");
      return;
    }

    setSubmitting(true);
    setNameError(null);
    setFormError(null);
    try {
      const payload = { name: trimmed, description: description.trim() || null };
      const saved = isEdit && scene
        ? await updateScene(scene.id, payload)
        : await createScene(payload);
      onSaved(saved);
    } catch (err) {
      if (err instanceof ApiError && err.code === "SCENE_NAME_EXISTS") {
        setNameError("同名评测集已经存在。");
      } else if (err instanceof ApiError) {
        setFormError(err.message);
      } else {
        setFormError("保存失败，请稍后重试。");
      }
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      title={isEdit ? "编辑评测集" : "创建评测集"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" form="evaluation-set-form" loading={submitting}>
            {isEdit ? "保存" : "创建"}
          </Button>
        </>
      }
    >
      <form id="evaluation-set-form" className={styles.form} onSubmit={handleSubmit} noValidate>
        {formError ? <ErrorPanel title="保存未成功" message={formError} /> : null}
        <TextField
          label="名称"
          name="name"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            if (nameError) setNameError(null);
          }}
          error={nameError}
          required
          disabled={submitting}
          hint="1–100 个字符"
        />
        <TextField
          label="描述（可选）"
          name="description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={submitting}
        />
      </form>
    </Dialog>
  );
}
