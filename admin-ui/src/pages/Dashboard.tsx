import { useEffect, useState } from "react";
import { Title, useNotify } from "react-admin";
import {
  Box,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Grid,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import StorefrontIcon from "@mui/icons-material/Storefront";
import SupportAgentIcon from "@mui/icons-material/SupportAgent";
import QuizIcon from "@mui/icons-material/Quiz";
import { apiUrl } from "../dataProvider";

interface Stat {
  shop_id: string;
  stat_date: string;
  total_sessions: number;
  faq_hits: number;
  llm_calls: number;
  escalations: number;
  faq_hit_rate: number;
}

function StatCard({
  title,
  value,
  icon,
  color,
}: {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <Card elevation={2}>
      <CardContent>
        <Box display="flex" alignItems="center" gap={2}>
          <Box sx={{ bgcolor: color, borderRadius: 2, p: 1.5, display: "flex", color: "white" }}>
            {icon}
          </Box>
          <Box>
            <Typography variant="h5" fontWeight="bold">{value}</Typography>
            <Typography variant="body2" color="text.secondary">{title}</Typography>
          </Box>
        </Box>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stat[]>([]);
  const [loading, setLoading] = useState(true);
  const notify = useNotify();
  const today = new Date().toISOString().split("T")[0];

  useEffect(() => {
    fetch(`${apiUrl}/dashboard?date=${today}`)
      .then((r) => r.json())
      .then((data) => { setStats(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(() => { notify("加载统计数据失败", { type: "error" }); setLoading(false); });
  }, [today, notify]);

  const totals = stats.reduce(
    (acc, s) => ({
      sessions: acc.sessions + s.total_sessions,
      faq: acc.faq + s.faq_hits,
      llm: acc.llm + s.llm_calls,
      escalations: acc.escalations + s.escalations,
    }),
    { sessions: 0, faq: 0, llm: 0, escalations: 0 }
  );

  return (
    <Box p={3}>
      <Title title="仪表盘" />
      <Typography variant="h5" fontWeight="bold" mb={3}>今日概览 · {today}</Typography>

      {loading ? (
        <Box display="flex" justifyContent="center" mt={4}><CircularProgress /></Box>
      ) : (
        <>
          <Grid container spacing={2} mb={4}>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <StatCard title="总会话数" value={totals.sessions} icon={<TrendingUpIcon />} color="#1976d2" />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <StatCard title="FAQ 命中" value={totals.faq} icon={<QuizIcon />} color="#2e7d32" />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <StatCard title="LLM 调用" value={totals.llm} icon={<SupportAgentIcon />} color="#ed6c02" />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, md: 3 }}>
              <StatCard title="转人工" value={totals.escalations} icon={<StorefrontIcon />} color="#d32f2f" />
            </Grid>
          </Grid>

          <Card elevation={2}>
            <CardHeader title="各店铺详情" />
            <CardContent sx={{ p: 0 }}>
              {stats.length === 0 ? (
                <Box p={3} textAlign="center">
                  <Typography color="text.secondary">今日暂无会话数据</Typography>
                </Box>
              ) : (
                <TableContainer component={Paper} elevation={0}>
                  <Table size="small">
                    <TableHead>
                      <TableRow sx={{ bgcolor: "grey.50" }}>
                        <TableCell>店铺 ID</TableCell>
                        <TableCell align="right">会话数</TableCell>
                        <TableCell align="right">FAQ 命中</TableCell>
                        <TableCell align="right">FAQ 命中率</TableCell>
                        <TableCell align="right">LLM 调用</TableCell>
                        <TableCell align="right">转人工</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {stats.map((s) => (
                        <TableRow key={s.shop_id} hover>
                          <TableCell><Chip label={s.shop_id} size="small" variant="outlined" /></TableCell>
                          <TableCell align="right">{s.total_sessions}</TableCell>
                          <TableCell align="right">{s.faq_hits}</TableCell>
                          <TableCell align="right">
                            <Chip
                              label={`${(s.faq_hit_rate * 100).toFixed(1)}%`}
                              size="small"
                              color={s.faq_hit_rate >= 0.8 ? "success" : "warning"}
                            />
                          </TableCell>
                          <TableCell align="right">{s.llm_calls}</TableCell>
                          <TableCell align="right">
                            {s.escalations > 0
                              ? <Chip label={s.escalations} size="small" color="error" />
                              : s.escalations}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </Box>
  );
}
